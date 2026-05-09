import polars as pl
import os
import sys
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
import dns.resolver
from typing import Set, Dict, List, Optional
import argparse
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

# --- Standard Library Protection ---
# CRITICAL: Ensure no file named 'csv.py' exists in the working directory to avoid import conflicts.
if (Path.cwd() / "csv.py").exists():
    print("FATAL ERROR: A file named 'csv.py' was found in your directory.")
    print("This conflicts with the Python standard library. Please rename it to something else (e.g., 'csv_utils.py').")
    sys.exit(1)

# --- Global Configuration & Constants ---
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "yopmail.com",
    "trashmail.com", "sharklasers.com", "10minutemail.com", "temp-mail.org",
    "disposable.com", "guerrillamail.biz", "guerrillamail.org"
}

# Standardized column aliases for heterogeneous CSV/Excel headers
ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address", "user_email", "email_id"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell", "whatsapp", "mobile_no.", "alternate_number"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday"],
    "age": ["age", "years", "current_age"],
    "gender": ["gender", "sex", "m/f", "gen"],
    "salary": ["salary", "salery", "current_salary", "ctc", "expected_salary"]
}

# Global MX Cache
mx_cache: Dict[str, bool] = {}

class DomainValidator:
    def __init__(self, max_workers: int = 60):
        self.max_workers = max_workers
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = 2.0
        self.resolver.timeout = 2.0

    def check_deliverability_single(self, domain: Optional[str]) -> tuple:
        """Atomic check for one domain with sanitization."""
        if not domain: return domain, False
        clean_domain = re.sub(r'[^\x20-\x7E]', '', str(domain)).lower().strip()

        if clean_domain in DISPOSABLE_DOMAINS:
            return clean_domain, False

        try:
            res = dns.resolver.Resolver()
            res.lifetime = 2.0
            res.timeout = 2.0
            res.resolve(clean_domain, 'MX')
            return clean_domain, True
        except Exception:
            return clean_domain, False

    def validate_domains(self, domains: List[str]) -> List[str]:
        """Parallelized MX lookup for speed optimization."""
        to_check = [d for d in domains if d and d not in mx_cache]
        if not to_check:
            return [d for d in domains if d and mx_cache.get(d) is True]

        logging.info(f"Checking {len(to_check)} unique domains in parallel...")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_domain = {executor.submit(self.check_deliverability_single, d): d for d in to_check}
            for future in as_completed(future_to_domain):
                domain, is_valid = future.result()
                mx_cache[domain] = is_valid

        return [d for d in domains if d and mx_cache.get(d) is True]

# --- Standalone Worker Functions ---

def get_cleaning_expressions():
    """Identifier normalization logic."""
    return [
        pl.col("email").str.replace_all(r"[^\x20-\x7E]", "").str.strip_chars().str.to_lowercase().alias("email"),
        pl.col("mobile").str.replace_all(r"[^\x20-\x7E]", "").str.replace_all(r"[\s\+\-\(\)\[\]]", "").alias("mobile")
    ]

def process_single_file_task(file_path: str, output_dir: str):
    """Worker task: Scans, standardizes and saves intermediate IPC."""
    try:
        temp_dir = Path(output_dir) / "temp_processed"
        temp_dir.mkdir(parents=True, exist_ok=True)

        path_obj = Path(file_path)
        file_name = path_obj.name
        target_path = temp_dir / f"{file_name}.ipc"

        # Support both .csv and .xlsx
        ext = path_obj.suffix.lower()
        if ext == '.csv':
            lf = pl.scan_csv(
                file_path,
                encoding="utf8-lossy",
                ignore_errors=True,
                infer_schema_length=2000,
                truncate_ragged_lines=True,
                null_values=["", "NA", "N/A", "null", "NULL"]
            )
        elif ext in ['.xlsx', '.xls']:
            # Excel files are read into memory first, then converted to LazyFrame
            # Note: requires 'fastexcel' or 'calamine' engine
            # FIX: Handle Excel formula errors (#NAME?) and large mobile numbers by casting everything to String early.
            df_excel = pl.read_excel(file_path, infer_schema_length=0)
            lf = df_excel.lazy()
        else:
            return f"ERROR: Unsupported extension {ext} for {file_path}"

        # Schema Alignment & Header Normalization
        orig_cols = lf.collect_schema().names()
        lf = lf.rename({c: c.lower() for c in orig_cols})
        cols = [c.lower() for c in orig_cols]

        mapping = {}
        for target, synonyms in ALIASES.items():
            match = next((c for c in cols if c.replace(" ", "_").replace(".", "_") in synonyms), None)
            if match:
                mapping[match] = target

        if mapping:
            lf = lf.rename(mapping)

        # Cast ALL columns to String for safety
        current_cols = lf.collect_schema().names()
        lf = lf.with_columns([pl.col(c).cast(pl.String) for c in current_cols])

        # Ensure mandatory columns exist
        for col in ["email", "mobile", "dob", "age", "gender", "salary"]:
            if col not in lf.collect_schema().names():
                lf = lf.with_columns(pl.lit(None).cast(pl.String).alias(col))

        lf = lf.with_columns(get_cleaning_expressions())

        # Mandatory filter: Email and Mobile must not be empty
        lf = lf.filter(
            pl.col("email").is_not_null() & (pl.col("email") != "") &
            pl.col("mobile").is_not_null() & (pl.col("mobile") != "")
        )

        df = lf.collect()
        if not df.is_empty():
            df.write_ipc(target_path)
            return str(target_path)
        return None

    except Exception as e:
        return f"ERROR: {file_path} -> {str(e)}"

# --- Global Aggregation Logic ---

def get_dob_age_expressions():
    """Production-grade DOB parsing and 2-digit year correction."""
    current_year = datetime.now().year

    dob_as_numeric = pl.col("dob").str.extract(r"^(\d{1,3})$").cast(pl.Int64)
    dob_is_age_fallback = pl.when(dob_as_numeric <= 100).then(dob_as_numeric).otherwise(None)

    parsed_dob = pl.coalesce([
        pl.col("dob").str.to_date("%d/%m/%Y", strict=False),
        pl.col("dob").str.to_date("%Y-%m-%d", strict=False),
        pl.col("dob").str.to_date("%d-%m-%Y", strict=False),
        pl.col("dob").str.to_date("%d/%m/%y", strict=False),
    ])

    # Pivot logic: 90 -> 1990
    fixed_dob = (
        pl.when(parsed_dob.dt.year() < 100)
        .then(
            pl.when(parsed_dob.dt.year() + 2000 > current_year)
            .then(parsed_dob.dt.offset_by("1900y"))
            .otherwise(parsed_dob.dt.offset_by("2000y"))
        )
        .when(parsed_dob.dt.year() > current_year)
        .then(parsed_dob.dt.offset_by("-100y"))
        .otherwise(parsed_dob)
    )

    explicit_age = pl.col("age").str.extract(r"(\d+)").cast(pl.Int64)
    calculated_age = (current_year - fixed_dob.dt.year()).fill_null(dob_is_age_fallback).fill_null(explicit_age)

    return [calculated_age.cast(pl.Int64).alias("calculated_age")]

def get_country_expressions():
    """Detect and normalize country-specific data."""
    return [
        pl.when(pl.col("mobile").str.starts_with("91") & (pl.col("mobile").str.len_chars() == 12))
        .then(pl.col("mobile").str.slice(2))
        .otherwise(pl.col("mobile"))
        .alias("norm_mobile"),

        pl.when(pl.col("mobile").str.starts_with("91") | pl.col("mobile").str.contains(r"^[6-9]\d{9}$"))
        .then(pl.lit("INDIA"))
        .when(pl.col("mobile").str.starts_with("1") & (pl.col("mobile").str.len_chars() == 11))
        .then(pl.lit("USA"))
        .otherwise(pl.lit("OTHER"))
        .alias("detected_country")
    ]

# --- Pipeline Main Class ---

class LeadsETL:
    def __init__(self, input_path: str, output_path: str):
        self.input_dir = Path(input_path)
        self.output_dir = Path(output_path)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[logging.FileHandler(self.output_dir / "pipeline.log"), logging.StreamHandler()]
        )
        self.checkpoint_file = self.output_dir / "checkpoint.json"
        self.processed_files = self._load_checkpoint()
        self.validator = DomainValidator()

    def _load_checkpoint(self) -> Set[str]:
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r") as f:
                    data = json.load(f)
                    return set(data) if isinstance(data, list) else set()
            except Exception: pass
        return set()

    def _save_checkpoint(self, filename: str):
        self.processed_files.add(filename)
        with open(self.checkpoint_file, "w") as f:
            json.dump(list(self.processed_files), f)

    def run(self):
        # Flexible file loading for .csv and .xlsx
        all_files = []
        for ext in ['*.csv', '*.CSV', '*.xlsx', '*.XLSX', '*.xls', '*.XLS']:
            all_files.extend([str(f) for f in self.input_dir.glob(ext)])

        all_files = sorted(list(set(all_files)))
        to_process = [f for f in all_files if f not in self.processed_files]

        if not to_process:
            logging.info("No new files found for processing.")
            return

        # Phase 1: Parallel Processing
        logging.info(f"Starting parallel processing of {len(to_process)} files...")
        ipc_files = []
        max_proc = min(multiprocessing.cpu_count(), len(to_process), 12)

        with ProcessPoolExecutor(max_workers=max_proc) as executor:
            future_to_file = {executor.submit(process_single_file_task, f, str(self.output_dir)): f for f in to_process}
            for future in as_completed(future_to_file):
                res = future.result()
                orig_file = future_to_file[future]
                if res and not str(res).startswith("ERROR"):
                    ipc_files.append(res)
                    self._save_checkpoint(orig_file)
                else:
                    logging.error(f"Worker failed for {orig_file}: {res}")

        if not ipc_files:
            logging.info("Initial phase produced no output data.")
            return

        # Phase 2: Global Logic & Deduplication
        logging.info("Merging intermediate results and applying global logic...")
        # FIX: diagonal concat for heterogeneous IPC schemas
        full_lf = pl.concat([pl.scan_ipc(f) for f in ipc_files], how="diagonal")

        # Deduplication
        full_lf = full_lf.unique(subset=["email"], maintain_order=True).unique(subset=["mobile"], maintain_order=True)

        full_lf = full_lf.with_columns(get_dob_age_expressions())
        full_lf = full_lf.with_columns(get_country_expressions())

        logging.info("Extracting unique domains for parallel validation...")
        unique_domains = (
            full_lf.select(domain=pl.col("email").str.extract(r"@([^@]+)$"))
            .unique()
            .collect(engine="streaming")
            .get_column("domain")
            .to_list()
        )

        valid_domains = self.validator.validate_domains(unique_domains)

        # Enforce Deliverability rules (Age filtering removed as per requirement)
        full_lf = full_lf.filter(
            pl.col("email").str.extract(r"@([^@]+)$").is_in(valid_domains)
        )

        india_lf = full_lf.filter(pl.col("detected_country") == "INDIA").filter(pl.col("norm_mobile").str.contains(r"^[6-9]\d{9}$"))
        usa_lf = full_lf.filter(pl.col("detected_country") == "USA")

        # Persistence
        self.persist(india_lf, "india_leads")
        self.persist(usa_lf, "usa_leads")

        # Cleanup
        logging.info("Cleaning up intermediate files...")
        for f in ipc_files:
            try: os.remove(f)
            except: pass
        try: os.rmdir(self.output_dir / "temp_processed")
        except: pass

        logging.info("Pipeline completed successfully.")

    def _sync_schema_and_collect(self, lf: pl.LazyFrame, table_name: str, db_path: Path) -> pl.DataFrame:
        """Bidirectional synchronization between DF and SQLite schemas."""
        df = lf.collect(engine="streaming")
        if df.is_empty() or not db_path.exists():
            return df

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            db_table_match = cursor.fetchone()
            if not db_table_match:
                return df

            real_table_name = db_table_match[0]
            cursor.execute(f'PRAGMA table_info("{real_table_name}")')
            db_cols = {row[1] for row in cursor.fetchall()}

            # Evolve DB schema
            for col in df.columns:
                if col not in db_cols:
                    logging.info(f"Evolving DB schema: Adding [{col}] to [{real_table_name}]")
                    cursor.execute(f'ALTER TABLE "{real_table_name}" ADD COLUMN "{col}" TEXT')
            conn.commit()

            # Evolve DF schema
            cursor.execute(f'PRAGMA table_info("{real_table_name}")')
            final_db_cols = [row[1] for row in cursor.fetchall()]
            missing_in_df = [col for col in final_db_cols if col not in df.columns]
            if missing_in_df:
                df = df.with_columns([pl.lit(None).cast(pl.String).alias(col) for col in missing_in_df])

            df = df.select(final_db_cols)

        except Exception as e:
            logging.error(f"Schema sync critical error for {table_name}: {e}")
        finally:
            conn.close()
        return df

    def persist(self, lf: pl.LazyFrame, name: str):
        """Focus on CSV and SQLite. Removed Excel export logic for high-volume safety."""
        db_path = self.output_dir / "leads_production.db"
        csv_path = self.output_dir / f"{name}.csv"

        try:
            df = self._sync_schema_and_collect(lf, name, db_path)
            if df.is_empty(): return

            # CSV Export
            df.write_csv(csv_path)
            logging.info(f"Successfully exported {name}.csv ({len(df)} records).")

            # SQLite Export (ADBC)
            df.write_database(
                table_name=name,
                connection=f"sqlite:///{db_path}",
                if_table_exists="append",
                engine="adbc"
            )
            logging.info(f"Successfully appended {name} to SQLite.")

        except Exception as e:
            logging.error(f"Persistence error for {name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Production-grade Leads ETL Pipeline")
    parser.add_argument("--input", required=True, help="Input directory path")
    parser.add_argument("--output", required=True, help="Output directory path")
    args = parser.parse_args()

    LeadsETL(args.input, args.output).run()
