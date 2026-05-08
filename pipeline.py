import polars as pl
import os
import json
import logging
import re
from datetime import datetime
from pathlib import Path
import dns.resolver
from typing import Set, Dict, List, Optional
import argparse

# --- Global Configuration & Constants ---
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "yopmail.com",
    "trashmail.com", "sharklasers.com", "10minutemail.com", "temp-mail.org",
    "disposable.com", "guerrillamail.biz", "guerrillamail.org"
}

ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address", "user_email", "email_id"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell", "whatsapp", "mobile_no.", "alternate_number"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday"],
    "age": ["age", "years", "current_age"]
}

# Global MX Cache (Rule 8)
mx_cache: Dict[str, bool] = {}

class DomainValidator:
    def __init__(self):
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = 2.0
        self.resolver.timeout = 2.0

    def check_deliverability(self, domain: str) -> bool:
        """Check MX records and block disposables (Rule 7, 8)."""
        if not domain: return False
        domain = domain.lower().strip()
        if domain in mx_cache: return mx_cache[domain]

        if domain in DISPOSABLE_DOMAINS:
            mx_cache[domain] = False
            return False

        try:
            self.resolver.resolve(domain, 'MX')
            mx_cache[domain] = True
        except Exception:
            mx_cache[domain] = False
        return mx_cache[domain]

# --- Processing Expressions ---

def get_cleaning_expressions():
    """Initial text normalization and bug fixes (Rule 6, 10)."""
    return [
        pl.col("email").str.strip_chars().str.to_lowercase().alias("email"),
        pl.col("mobile").str.replace_all(r"[\s\+\-\(\)\[\]]", "").alias("mobile")
    ]

def get_dob_age_expressions():
    """Fixes 2-digit years and numeric age bug (Rule 1, 2)."""
    current_year = datetime.now().year

    # 1. Detect if DOB is actually an age (Numeric <= 100) (Rule 2)
    dob_as_numeric = pl.col("dob").str.extract(r"^(\d{1,3})$").cast(pl.Int64)
    dob_is_age_fallback = pl.when(dob_as_numeric <= 100).then(dob_as_numeric).otherwise(None)

    # 2. Parse DOB formats safely
    parsed_dob = pl.coalesce([
        pl.col("dob").str.to_date("%d/%m/%Y", strict=False),
        pl.col("dob").str.to_date("%Y-%m-%d", strict=False),
        pl.col("dob").str.to_date("%d-%m-%Y", strict=False),
        pl.col("dob").str.to_date("%d/%m/%y", strict=False),
    ])

    # 3. Fix 2-digit year (Rule 1: 90 -> 1990)
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

    # 4. Final Age logic (Age <= 40)
    explicit_age = pl.col("age").str.extract(r"(\d+)").cast(pl.Int64)
    calculated_age = (current_year - fixed_dob.dt.year()).fill_null(dob_is_age_fallback).fill_null(explicit_age)

    return [calculated_age.alias("calculated_age")]

def get_country_expressions():
    """Handle country code and detection (Rule 10)."""
    return [
        # India normalization
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

# --- Pipeline Class ---

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

    def map_headers(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Standardizes headers and FIXES Schema Mismatch by casting ALL to String."""
        cols = lf.collect_schema().names()
        mapping = {}
        for target, synonyms in ALIASES.items():
            match = next((c for c in cols if c.lower().replace(" ", "_") in synonyms), None)
            if match:
                mapping[match] = target

        if mapping:
            lf = lf.rename(mapping)

        # FIX: Schema Mismatch (concat error). Cast every column to String to ensure diagonal concat works.
        current_cols = lf.collect_schema().names()
        lf = lf.with_columns([pl.col(c).cast(pl.String) for c in current_cols])

        # Ensure mandatory internal columns exist
        for col in ["email", "mobile", "dob", "age"]:
            if col not in lf.collect_schema().names():
                lf = lf.with_columns(pl.lit(None).cast(pl.String).alias(col))

        return lf

    def run(self):
        files = sorted([str(f) for f in self.input_dir.glob("*.csv")])
        to_process = [f for f in files if f not in self.processed_files]

        if not to_process:
            logging.info("No new files found.")
            return

        lazy_frames = []
        for file_path in to_process:
            try:
                lf = pl.scan_csv(file_path, infer_schema_length=1000, ignore_errors=True)
                if lf.collect_schema().len() == 0:
                    continue

                lf = self.map_headers(lf)
                lf = lf.with_columns(get_cleaning_expressions())

                # Rule 5: Drop null/blank email OR mobile
                lf = lf.filter(
                    pl.col("email").is_not_null() & (pl.col("email") != "") &
                    pl.col("mobile").is_not_null() & (pl.col("mobile") != "")
                )

                lazy_frames.append(lf)
                self._save_checkpoint(file_path)
            except Exception as e:
                logging.error(f"Error scanning {file_path}: {e}")

        if not lazy_frames: return

        logging.info("Merging and processing dataset...")
        # Rule 11: Global Diagonal Concat (Safe now due to String casting)
        full_lf = pl.concat(lazy_frames, how="diagonal")

        # Global Deduplication (Rule 11)
        full_lf = full_lf.unique(subset=["email"], maintain_order=True).unique(subset=["mobile"], maintain_order=True)

        full_lf = full_lf.with_columns(get_dob_age_expressions())
        full_lf = full_lf.with_columns(get_country_expressions())

        # MX Caching deliverability check (Rule 8, 14)
        logging.info("Validating email domains via MX cache...")
        unique_domains = (
            full_lf.select(domain=pl.col("email").str.extract(r"@([^@]+)$"))
            .unique()
            .collect()
            .get_column("domain")
            .to_list()
        )
        valid_domains = [d for d in unique_domains if self.validator.check_deliverability(d)]

        # Strict Final Validation
        full_lf = full_lf.filter(
            (pl.col("calculated_age") <= 40) &
            (pl.col("email").str.extract(r"@([^@]+)$").is_in(valid_domains))
        )

        # Country Splits
        india_lf = full_lf.filter(pl.col("detected_country") == "INDIA").filter(pl.col("norm_mobile").str.contains(r"^[6-9]\d{9}$"))
        usa_lf = full_lf.filter(pl.col("detected_country") == "USA")

        self.persist(india_lf, "india_leads")
        self.persist(usa_lf, "usa_leads")

        logging.info("Pipeline completed.")

    def persist(self, lf: pl.LazyFrame, name: str):
        """Safe SQLite append and multi-format export."""
        db_path = self.output_dir / "leads_production.db"
        csv_path = self.output_dir / f"{name}.csv"
        xlsx_path = self.output_dir / f"{name}.xlsx"

        try:
            df = lf.collect(engine="streaming")
            if df.is_empty(): return

            df.write_csv(csv_path)

            # Rule 3: SQLite Append only
            df.write_database(
                table_name=name,
                connection=f"sqlite:///{db_path}",
                if_table_exists="append",
                engine="adbc"
            )

            # Excel export (Rule 13)
            df.write_excel(xlsx_path)

            logging.info(f"Exported {name} with {len(df)} records.")
        except Exception as e:
            logging.error(f"Persistence error for {name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    LeadsETL(args.input, args.output).run()
