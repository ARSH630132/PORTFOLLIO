import polars as pl
import os
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

# --- Global Configuration & Constants ---
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "yopmail.com",
    "trashmail.com", "sharklasers.com", "10minutemail.com", "temp-mail.org",
    "disposable.com", "guerrillamail.biz", "guerrillamail.org"
}

# Standardized column aliases for heterogeneous CSV headers
ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address", "user_email", "email_id", "email_address"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell", "whatsapp", "mobile_no.", "alternate_number"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday"],
    "age": ["age", "years", "current_age"]
}

# Global MX Cache (utilized in Phase 2)
mx_cache: Dict[str, bool] = {}

class DomainValidator:
    def __init__(self, max_workers: int = 50):
        self.max_workers = max_workers
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = 2.0
        self.resolver.timeout = 2.0

    def check_deliverability_single(self, domain: Optional[str]) -> tuple:
        """Atomic check for one domain with sanitization."""
        if not domain: return domain, False
        # Remove any non-ascii artifacts that might cause DNS/UTF-8 issues
        clean_domain = re.sub(r'[^\x20-\x7E]', '', str(domain)).lower().strip()

        if clean_domain in DISPOSABLE_DOMAINS:
            return clean_domain, False

        try:
            # Thread-safe resolver usage
            res = dns.resolver.Resolver()
            res.lifetime = 2.0
            res.timeout = 2.0
            res.resolve(clean_domain, 'MX')
            return clean_domain, True
        except Exception:
            return clean_domain, False

    def validate_domains(self, domains: List[str]) -> List[str]:
        """Parallelized MX lookup to drastically speed up processing."""
        to_check = [d for d in domains if d and d not in mx_cache]
        logging.info(f"Checking {len(to_check)} unique domains in parallel...")

        valid_domains = [d for d in domains if d and mx_cache.get(d) is True]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_domain = {executor.submit(self.check_deliverability_single, d): d for d in to_check}
            for future in as_completed(future_to_domain):
                domain, is_valid = future.result()
                mx_cache[domain] = is_valid
                if is_valid:
                    valid_domains.append(domain)

        return valid_domains

# --- Standalone Worker Functions ---

def get_cleaning_expressions():
    """Identifier normalization logic shared across processes."""
    return [
        pl.col("email").str.replace_all(r"[^\x20-\x7E]", "").str.strip_chars().str.to_lowercase().alias("email"),
        pl.col("mobile").str.replace_all(r"[^\x20-\x7E]", "").str.replace_all(r"[\s\+\-\(\)\[\]]", "").alias("mobile")
    ]

def process_single_file_task(file_path: str, output_dir: str):
    """
    Independent worker task for Multiprocessing.
    Handles: Scanning, schema normalization, type casting, and intermediate persistence.
    """
    try:
        temp_dir = Path(output_dir) / "temp_processed"
        temp_dir.mkdir(parents=True, exist_ok=True)

        file_name = Path(file_path).name
        target_path = temp_dir / f"{file_name}.ipc"

        # 1. Scan with high tolerance for encoding/structure issues
        lf = pl.scan_csv(
            file_path,
            encoding="utf8-lossy",
            ignore_errors=True,
            infer_schema_length=2000,
            truncate_ragged_lines=True,
            null_values=["", "NA", "N/A", "null", "NULL"]
        )

        # 2. Schema Alignment
        cols = lf.collect_schema().names()
        mapping = {}
        for target, synonyms in ALIASES.items():
            # Robust mapping for varying header styles
            match = next((c for c in cols if c.lower().replace(" ", "_").replace(".", "_") in synonyms), None)
            if match:
                mapping[match] = target

        if mapping:
            lf = lf.rename(mapping)

        # Cast ALL columns to String to ensure diagonal concat succeeds without schema errors
        current_cols = lf.collect_schema().names()
        lf = lf.with_columns([pl.col(c).cast(pl.String) for c in current_cols])

        # Ensure standard columns exist for logical consistency
        for col in ["email", "mobile", "dob", "age"]:
            if col not in lf.collect_schema().names():
                lf = lf.with_columns(pl.lit(None).cast(pl.String).alias(col))

        # 3. Apply cleaning logic
        lf = lf.with_columns(get_cleaning_expressions())

        # 4. Mandatory column filter (Email/Mobile non-empty)
        lf = lf.filter(
            pl.col("email").is_not_null() & (pl.col("email") != "") &
            pl.col("mobile").is_not_null() & (pl.col("mobile") != "")
        )

        # 5. Save to binary IPC for extremely fast aggregation in main process
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

    return [calculated_age.alias("calculated_age")]

def get_country_expressions():
    """Detect and normalize country-specific data (India/USA)."""
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
                with open(self.checkpoint_file, "r") as f: return set(json.load(f))
            except Exception: pass
        return set()

    def _save_checkpoint(self, filename: str):
        self.processed_files.add(filename)
        with open(self.checkpoint_file, "w") as f:
            json.dump(list(self.processed_files), f)

    def run(self):
        files = sorted([str(f) for f in self.input_dir.glob("*.csv")])
        to_process = [f for f in files if f not in self.processed_files]

        if not to_process:
            logging.info("No new files to process.")
            return

        # Phase 1: High-Speed Parallel File Processing
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
            logging.info("Initial processing phase produced no output data.")
            return

        # Phase 2: Global Logic & Deduplication
        logging.info("Merging intermediate results and applying global logic...")
        full_lf = pl.scan_ipc(ipc_files)

        # Global uniqueness on Email/Mobile
        full_lf = full_lf.unique(subset=["email"], maintain_order=True).unique(subset=["mobile"], maintain_order=True)

        full_lf = full_lf.with_columns(get_dob_age_expressions())
        full_lf = full_lf.with_columns(get_country_expressions())

        # Parallelized Deliverability Check
        logging.info("Extracting unique domains for parallel validation...")
        unique_domains = (
            full_lf.select(domain=pl.col("email").str.extract(r"@([^@]+)$"))
            .unique()
            .collect(engine="streaming")
            .get_column("domain")
            .to_list()
        )

        valid_domains = self.validator.validate_domains(unique_domains)

        # Enforce Age and Deliverability rules
        full_lf = full_lf.filter(
            (pl.col("calculated_age") <= 40) &
            (pl.col("email").str.extract(r"@([^@]+)$").is_in(valid_domains))
        )

        # Splitting
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

    def _ensure_sqlite_schema(self, df: pl.DataFrame, table_name: str, db_path: Path):
        """Fixes 'did not find column' error by auto-evolving SQLite schema (Rule 3)."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone(): return # Table creation will happen in write_database

            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            for col in df.columns:
                if col not in existing_cols:
                    logging.info(f"Evolving schema: Adding column [{col}] to SQLite table [{table_name}]")
                    # SQLite requires quoting identifiers to handle special characters in headers
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT')
            conn.commit()
        except Exception as e:
            logging.warning(f"Schema evolution failed for {table_name}: {e}")
        finally:
            conn.close()

    def persist(self, lf: pl.LazyFrame, name: str):
        """Robust persistence with schema evolution and multi-format support."""
        db_path = self.output_dir / "leads_production.db"
        csv_path = self.output_dir / f"{name}.csv"
        xlsx_path = self.output_dir / f"{name}.xlsx"

        try:
            df = lf.collect(engine="streaming")
            if df.is_empty(): return

            df.write_csv(csv_path)

            # Auto-evolve SQLite schema if table exists but new columns are detected
            if db_path.exists():
                self._ensure_sqlite_schema(df, name, db_path)

            # High-performance append via ADBC
            df.write_database(
                table_name=name,
                connection=f"sqlite:///{db_path}",
                if_table_exists="append",
                engine="adbc"
            )

            # Safe Excel export
            df.write_excel(xlsx_path)

            logging.info(f"Exported {name}: {len(df)} records.")
        except Exception as e:
            logging.error(f"Persistence error for {name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    LeadsETL(args.input, args.output).run()
