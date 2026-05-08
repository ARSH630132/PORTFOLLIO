import polars as pl
import os
import json
import logging
import re
from datetime import datetime
import dns.resolver
from pathlib import Path
from typing import Set, List, Dict, Optional
import argparse

# --- Global Configuration ---
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "sharklasers.com",
    "10minutemail.com", "temp-mail.org", "guerrillamail.biz", "trashmail.com"
}

# Column aliases to handle varying source schemas
ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address", "user_email"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell", "whatsapp"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday", "birth_day"],
    "age": ["age", "years", "current_age"]
}

# --- Infrastructure & Utilities ---

def setup_logging(output_dir: Path):
    log_file = output_dir / "pipeline.log"
    error_log = output_dir / "error_log.txt"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    err_logger = logging.getLogger('error_logger')
    err_logger.propagate = False
    if not err_logger.handlers:
        err_logger.addHandler(logging.FileHandler(error_log))
    return err_logger

class CheckpointManager:
    def __init__(self, file_path: Path):
        self.path = file_path
        self.processed = self._load()

    def _load(self) -> Set[str]:
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    return set(json.load(f))
            except Exception as e:
                logging.warning(f"Checkpoint load failed: {e}")
        return set()

    def save(self, file_path: str):
        self.processed.add(file_path)
        with open(self.path, "w") as f:
            json.dump(list(self.processed), f)

# --- DNS / MX Domain Validation ---

class DomainValidator:
    def __init__(self):
        self.cache: Dict[str, bool] = {}
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = 2.0
        self.resolver.timeout = 2.0

    def is_valid(self, domain: Optional[str]) -> bool:
        if not domain: return False
        domain = domain.lower().strip()
        if domain in self.cache: return self.cache[domain]
        if domain in DISPOSABLE_DOMAINS:
            self.cache[domain] = False
            return False

        try:
            self.resolver.resolve(domain, 'MX')
            self.cache[domain] = True
        except Exception:
            self.cache[domain] = False
        return self.cache[domain]

# --- Polars Logic Components ---

def get_cleaning_expressions():
    """Returns a list of expressions for initial cleaning and normalization."""

    # 1. Email Normalization
    email_clean = (
        pl.col("email")
        .str.strip_chars()
        .str.to_lowercase()
        .replace("", None)
    )

    # 2. Mobile Cleaning
    mobile_clean = (
        pl.col("mobile")
        .cast(pl.String)
        .str.replace_all(r"[\s\+\-\(\)\[\]]", "")
        .str.replace(r"^91([6-9]\d{9})$", r"$1") # Normalize Indian +91
        .replace("", None)
    )

    return [
        email_clean.alias("email"),
        mobile_clean.alias("mobile")
    ]

def get_validation_expressions():
    """Returns expressions for strict identifier validation."""
    email_regex = r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
    indian_mobile_regex = r"^[6-9]\d{9}$"

    # Email Format & Disposable Check
    email_domain = pl.col("email").str.extract(r"@([^@]+)$")

    email_format_ok = (
        pl.col("email").is_not_null() &
        pl.col("email").str.contains(email_regex) &
        ~email_domain.is_in(list(DISPOSABLE_DOMAINS))
    ).fill_null(False)

    # Mobile Validation (Indian vs Foreign)
    mobile_is_indian = pl.col("mobile").str.contains(indian_mobile_regex)
    mobile_is_foreign = (
        pl.col("mobile").is_not_null() &
        (pl.col("mobile").str.len_chars() >= 7) &
        ~mobile_is_indian
    )

    mobile_ok = (mobile_is_indian | mobile_is_foreign).fill_null(False)

    return [
        email_format_ok.alias("email_format_ok"),
        mobile_ok.alias("mobile_ok"),
        email_domain.alias("email_domain")
    ]

def get_dob_age_expressions():
    """Complex logic for parsing DOB, fixing 2-digit years, and handling 'age-in-dob' edge cases."""
    current_year = datetime.now().year

    # Check if DOB string is actually a numeric age (<= 100)
    dob_as_numeric = pl.col("dob").str.extract(r"^(\d{1,2})$").cast(pl.Int64)

    # Parse valid DOB formats
    parsed_dob = pl.coalesce([
        pl.col("dob").str.to_date("%d/%m/%Y", strict=False),
        pl.col("dob").str.to_date("%Y-%m-%d", strict=False),
        pl.col("dob").str.to_date("%d-%m-%Y", strict=False),
        pl.col("dob").str.to_date("%d/%m/%y", strict=False),
    ])

    # Fix 2-digit year logic
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

    # Merge explicit age column with age-found-in-dob
    explicit_age = pl.col("age").str.extract(r"(\d+)").cast(pl.Int64)
    final_age = (current_year - fixed_dob.dt.year()).fill_null(dob_as_numeric).fill_null(explicit_age)

    return [
        fixed_dob.alias("cleaned_dob"),
        final_age.alias("calculated_age")
    ]

# --- Pipeline Core ---

class LeadsPipeline:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.err_logger = setup_logging(self.output_dir)
        self.checkpoint = CheckpointManager(self.output_dir / "checkpoint.json")
        self.domain_validator = DomainValidator()

    def normalize_header(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_").strip()

    def map_schema(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Aligns various CSV headers to a standard schema without losing original columns."""
        cols = lf.collect_schema().names()

        rename_map = {}
        for standard, aliases in ALIASES.items():
            match = next((c for c in cols if self.normalize_header(c) in [self.normalize_header(a) for a in aliases]), None)
            if match and match != standard:
                # If a standard name already exists in a different case, rename it to standard
                rename_map[match] = standard

        if rename_map:
            lf = lf.rename(rename_map)

        # Ensure mandatory columns exist as String
        existing = lf.collect_schema().names()
        for col in ["email", "mobile", "dob", "age"]:
            if col not in existing:
                lf = lf.with_columns(pl.lit(None).cast(pl.String).alias(col))
            else:
                lf = lf.with_columns(pl.col(col).cast(pl.String))

        return lf

    def process_files(self) -> Optional[pl.LazyFrame]:
        all_csvs = sorted([str(f) for f in self.input_dir.glob("*.csv")])
        to_process = [f for f in all_csvs if f not in self.checkpoint.processed]

        if not to_process:
            logging.info("No new files found for processing.")
            return None

        lazy_frames = []
        for f in to_process:
            try:
                lf = pl.scan_csv(f, infer_schema_length=1000, ignore_errors=True)
                if not lf.collect_schema().names():
                    logging.warning(f"Empty or corrupted file skipped: {f}")
                    continue

                lf = self.map_schema(lf)

                # Apply data integrity rule: Drop only if both email and mobile are null
                lf = lf.filter(~(pl.col("email").is_null() & pl.col("mobile").is_null()))

                # Apply initial cleaning
                lf = lf.with_columns(get_cleaning_expressions())

                lazy_frames.append(lf)
                self.checkpoint.save(f)
            except Exception as e:
                self.err_logger.error(f"Failed to scan file {f}: {e}")

        if not lazy_frames: return None
        return pl.concat(lazy_frames, how="diagonal")

    def run(self):
        logging.info("Starting leads processing pipeline...")

        full_lf = self.process_files()
        if full_lf is None: return

        # --- Global Deduplication Phase 1 (Normalization-based) ---
        logging.info("Applying global cleaning and deduplication...")

        # To handle 100M+ rows, we perform operations lazily
        # 1. Email Dedup (keep first record for each unique identifier)
        null_emails = full_lf.filter(pl.col("email").is_null())
        valid_emails = full_lf.filter(pl.col("email").is_not_null()).unique(subset=["email"], maintain_order=True)
        full_lf = pl.concat([null_emails, valid_emails])

        # 2. Mobile Dedup
        null_mobiles = full_lf.filter(pl.col("mobile").is_null())
        valid_mobiles = full_lf.filter(pl.col("mobile").is_not_null()).unique(subset=["mobile"], maintain_order=True)
        full_lf = pl.concat([null_mobiles, valid_mobiles])

        # --- Validation and Domain Verification ---
        full_lf = full_lf.with_columns(get_validation_expressions())

        # Efficient MX Lookup on Unique Domains only
        logging.info("Performing MX lookup on unique domains...")
        unique_domains = (
            full_lf.filter(pl.col("email_format_ok"))
            .select("email_domain")
            .unique()
            .collect()
            .get_column("email_domain")
            .to_list()
        )

        valid_domains = [d for d in unique_domains if self.domain_validator.is_valid(d)]

        full_lf = full_lf.with_columns(
            email_ok = pl.col("email_format_ok") & pl.col("email_domain").is_in(valid_domains)
        )

        # Integrity Check: Keep rows if either identifier is valid
        full_lf = full_lf.filter(pl.col("email_ok") | pl.col("mobile_ok"))

        # --- DOB and Age Processing ---
        logging.info("Calculating ages and filtering...")
        full_lf = full_lf.with_columns(get_dob_age_expressions())

        # Filter age > 40 where valid
        full_lf = full_lf.filter(
            (pl.col("calculated_age").is_null()) | (pl.col("calculated_age") > 40)
        )

        # --- Exporting Phase ---
        final_csv = self.output_dir / "final_clean.csv"
        db_path = self.output_dir / "leads.db"

        logging.info(f"Streaming final dataset to {final_csv}...")
        try:
            full_lf.sink_csv(final_csv)
        except Exception as e:
            # Fallback for complex plans that don't support sink
            full_lf.collect(engine="streaming").write_csv(final_csv)

        # Chunked SQLite Persistence
        logging.info(f"Persisting data to SQLite: {db_path}")
        self.persist_to_sqlite(final_csv, db_path)

        logging.info("Pipeline executed successfully.")

    def persist_to_sqlite(self, csv_path: Path, db_path: Path):
        """Reads the final CSV in chunks and appends to SQLite using ADBC driver."""
        batch_size = 100_000
        table_name = "leads"
        if_exists = "append" if db_path.exists() else "replace"

        try:
            reader = pl.read_csv_batched(csv_path, batch_size=batch_size)
            batches = reader.next_batches(1)
            total_rows = 0

            while batches:
                for batch in batches:
                    batch.write_database(
                        table_name=table_name,
                        connection=f"sqlite:///{db_path}",
                        if_table_exists=if_exists,
                        engine="adbc"
                    )
                    if_exists = "append"
                    total_rows += len(batch)

                logging.info(f"Appended {total_rows} rows to SQLite...")
                batches = reader.next_batches(1)
        except Exception as e:
            self.err_logger.error(f"Database write failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Production-grade Leads Processing Pipeline")
    parser.add_argument("--input", required=True, help="Folder containing source CSV files")
    parser.add_argument("--output", default="output", help="Target output directory")
    args = parser.parse_args()

    pipeline = LeadsPipeline(args.input, args.output)
    pipeline.run()
