import polars as pl
import os
import json
import logging
import re
from datetime import datetime
import dns.resolver
from pathlib import Path
import sqlite3
import argparse
from typing import Set

# --- Configuration & Constants ---
LOG_FILE = "pipeline.log"
ERROR_LOG = "error_log.txt"
CHECKPOINT_FILE = "checkpoint.json"
FINAL_CSV = "final_clean.csv"
DB_FILE = "leads.db"
DISPOSABLE_DOMAINS = {"mailinator.com", "tempmail.com", "guerrillamail.com", "sharklasers.com", "10minutemail.com"}

# Column Aliases Mapping
ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday"],
    "age": ["age", "years"]
}

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
error_logger = logging.getLogger('error_logger')
error_logger.propagate = False
error_logger.addHandler(logging.FileHandler(ERROR_LOG))

# --- Cleaning Helpers (Polars Expressions) ---

def clean_email_expr():
    return pl.col("email").str.strip_chars().str.to_lowercase()

def validate_email_format_expr():
    email_regex = r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
    return pl.col("email").str.contains(email_regex)

def clean_mobile_expr():
    return (
        pl.col("mobile")
        .cast(pl.String)
        .str.replace_all(r"[\s\+\-\(\)]", "")
        .str.replace(r"^91([6-9]\d{9})$", r"$1")
    )

def validate_indian_mobile_expr():
    return pl.col("mobile").str.contains(r"^[6-9]\d{9}$")

def parse_dob_expr():
    return pl.coalesce([
        pl.col("dob").str.to_date("%d/%m/%Y", strict=False),
        pl.col("dob").str.to_date("%Y-%m-%d", strict=False),
        pl.col("dob").str.to_date("%d-%m-%Y", strict=False),
        pl.col("dob").str.to_date("%d/%m/%y", strict=False),
    ])

def fix_2_digit_year(date_col):
    current_year = datetime.now().year
    return (
        pl.when(date_col.dt.year() < 100)
        .then(
            pl.when(date_col.dt.year() + 2000 > current_year)
            .then(date_col.dt.offset_by("1900y"))
            .otherwise(date_col.dt.offset_by("2000y"))
        )
        .when(date_col.dt.year() > current_year)
        .then(date_col.dt.offset_by("-100y"))
        .otherwise(date_col)
    )

# --- Global MX Cache ---
mx_cache = {}

def check_mx(domain):
    if not domain: return False
    domain = domain.lower().strip()
    if domain in mx_cache: return mx_cache[domain]
    if domain in DISPOSABLE_DOMAINS:
        mx_cache[domain] = False
        return False
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 2
        resolver.timeout = 2
        resolver.resolve(domain, 'MX')
        mx_cache[domain] = True
    except Exception:
        mx_cache[domain] = False
    return mx_cache[domain]

# --- Checkpoint Management ---
def load_checkpoint():
    if Path(CHECKPOINT_FILE).exists():
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            logging.warning("Failed to load checkpoint file.")
    return set()

def save_checkpoint(processed_files: Set[str]):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(list(processed_files), f)

# --- Processing Logic ---

def normalize_header(name):
    return name.lower().replace(" ", "_").replace("-", "_").strip()

def map_schema(df_lazy):
    schema = df_lazy.collect_schema()
    cols = schema.names()

    new_cols = {}
    for standard, aliases in ALIASES.items():
        match = next((c for c in cols if normalize_header(c) in [normalize_header(a) for a in aliases]), None)
        if match:
            new_cols[standard] = pl.col(match).cast(pl.String)
        else:
            new_cols[standard] = pl.lit(None).cast(pl.String)

    # Drop existing standard-named columns to avoid duplicates before adding them back
    cols_to_drop = [c for c in ["email", "mobile", "dob", "age"] if c in cols]
    df_lazy = df_lazy.drop(cols_to_drop)

    df_lazy = df_lazy.with_columns(**new_cols)

    # Normalize values to null if they are empty strings
    df_lazy = df_lazy.with_columns([
        pl.when(pl.col(c) == "").then(None).otherwise(pl.col(c)).alias(c)
        for c in ["email", "mobile", "dob", "age"]
    ])

    return df_lazy

def process_file(filepath):
    try:
        df = pl.scan_csv(filepath, infer_schema_length=1000, ignore_errors=True)
        if len(df.collect_schema().names()) == 0:
            return None
        df = map_schema(df)
        df = df.filter(~(pl.col("email").is_null() & pl.col("mobile").is_null()))
        df = df.with_columns([clean_email_expr(), clean_mobile_expr()])
        return df
    except Exception as e:
        error_logger.error(f"Error processing {filepath}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="output")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    processed_files = load_checkpoint()
    all_files = sorted([str(f) for f in input_path.glob("*.csv")])
    files_to_process = [f for f in all_files if f not in processed_files]

    if not files_to_process:
        logging.info("No new files.")
        return

    lazy_frames = []
    for f in files_to_process:
        lf = process_file(f)
        if lf is not None:
            lazy_frames.append(lf)
            processed_files.add(f)
            save_checkpoint(processed_files)

    if not lazy_frames:
        logging.info("No data.")
        return

    full_df = pl.concat(lazy_frames, how="diagonal")

    # Deduplication
    null_emails = full_df.filter(pl.col("email").is_null())
    valid_emails = full_df.filter(pl.col("email").is_not_null()).unique(subset=["email"])
    full_df = pl.concat([null_emails, valid_emails])

    null_mobiles = full_df.filter(pl.col("mobile").is_null())
    valid_mobiles = full_df.filter(pl.col("mobile").is_not_null()).unique(subset=["mobile"])
    full_df = pl.concat([null_mobiles, valid_mobiles])

    # Validation Flags
    full_df = full_df.with_columns(
        email_domain = pl.col("email").str.extract(r"@([^@]+)$")
    ).with_columns(
        email_format_ok = (pl.col("email").is_not_null() & validate_email_format_expr() & ~pl.col("email_domain").is_in(list(DISPOSABLE_DOMAINS))).fill_null(False),
        mobile_ok = (pl.col("mobile").is_not_null() & validate_indian_mobile_expr()).fill_null(False)
    )

    # MX Check
    logging.info("MX Lookup...")
    unique_domains = full_df.filter(pl.col("email_format_ok")).select("email_domain").unique().collect().get_column("email_domain").to_list()
    valid_domains = [d for d in unique_domains if check_mx(d)]
    full_df = full_df.with_columns(email_ok = pl.col("email_format_ok") & pl.col("email_domain").is_in(valid_domains))

    full_df = full_df.filter(pl.col("email_ok") | pl.col("mobile_ok"))

    # DOB/Age
    current_year = datetime.now().year
    full_df = full_df.with_columns(
        parsed_dob = fix_2_digit_year(parse_dob_expr()),
        age_numeric = pl.col("age").str.extract(r"(\d+)").cast(pl.Int64)
    ).with_columns(
        calculated_age = (current_year - pl.col("parsed_dob").dt.year()).fill_null(pl.col("age_numeric"))
    ).filter((pl.col("calculated_age").is_null()) | (pl.col("calculated_age") > 40))

    # Persistence
    final_csv = output_path / FINAL_CSV
    db_file = output_path / DB_FILE

    logging.info(f"Sinking to {final_csv}...")
    full_df.sink_csv(final_csv)

    logging.info(f"Writing to SQLite {db_file}...")
    batch_size = 100_000

    def chunked_db_write(csv_path, db_path, table_name, chunk_size):
        if_exists = "replace"
        reader = pl.read_csv_batched(csv_path, batch_size=chunk_size)

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

            logging.info(f"Wrote {total_rows} rows to DB...")
            batches = reader.next_batches(1)

    chunked_db_write(final_csv, db_file, "leads", batch_size)
    logging.info("Done.")

if __name__ == "__main__":
    main()
