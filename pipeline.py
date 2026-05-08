import polars as pl
from datetime import datetime
from pathlib import Path
import argparse
import json
import logging

# --- Configuration ---
ALIASES = {
    "email": ["email", "e-mail", "mail_id", "email_address", "user_email"],
    "mobile": ["mobile", "phone", "contact", "mobile_number", "phone_number", "cell", "whatsapp"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthday"],
    "age": ["age", "years"]
}

def normalize_header(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_").strip()

def get_cleaning_expressions():
    """Applies strict normalization: stripping, lowercase, and symbol removal."""
    return [
        pl.col("email").cast(pl.String).str.strip_chars().str.to_lowercase().alias("email"),
        pl.col("mobile").cast(pl.String).str.strip_chars().str.replace_all(r"[\s\+\-\(\)\[\]]", "").alias("mobile")
    ]

def get_dob_age_expressions():
    """Derives age from multiple DOB formats with fallback to explicit age column."""
    current_year = datetime.now().year

    # 1. Parse DOB strings into Date objects
    parsed_dob = pl.coalesce([
        pl.col("dob").str.to_date("%d/%m/%Y", strict=False),
        pl.col("dob").str.to_date("%Y-%m-%d", strict=False),
        pl.col("dob").str.to_date("%d-%m-%Y", strict=False),
        pl.col("dob").str.to_date("%d/%m/%y", strict=False),
    ])

    # 2. Correct 2-digit years
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

    # 3. Handle explicit age column
    explicit_age = pl.col("age").str.extract(r"(\d+)").cast(pl.Int64)

    # 4. Final age calculation
    calculated_age = (current_year - fixed_dob.dt.year()).fill_null(explicit_age)

    return [calculated_age.alias("calculated_age")]

class ProductionLeadsFilter:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[logging.FileHandler(self.output_dir / "pipeline.log"), logging.StreamHandler()]
        )
        self.checkpoint_path = self.output_dir / "checkpoint.json"
        self.processed = self._load_checkpoint()

    def _load_checkpoint(self):
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, "r") as f: return set(json.load(f))
            except Exception: pass
        return set()

    def map_schema(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Aligns source headers to internal standard schema."""
        cols = lf.collect_schema().names()
        new_cols = {}
        for standard, aliases in ALIASES.items():
            match = next((c for c in cols if normalize_header(c) in [normalize_header(a) for a in aliases]), None)
            new_cols[standard] = pl.col(match).cast(pl.String) if match else pl.lit(None).cast(pl.String)
        return lf.drop([c for c in ALIASES.keys() if c in cols]).with_columns(**new_cols)

    def run(self):
        csv_files = sorted([str(f) for f in self.input_dir.glob("*.csv")])
        to_process = [f for f in csv_files if f not in self.processed]
        if not to_process:
            logging.info("No new files found.")
            return

        lazy_frames = []
        for f in to_process:
            try:
                lf = pl.scan_csv(f, infer_schema_length=1000, ignore_errors=True)
                lf = self.map_schema(lf)
                lf = lf.with_columns(get_cleaning_expressions())
                lazy_frames.append(lf)
            except Exception as e:
                logging.error(f"Failed to scan {f}: {e}")

        if not lazy_frames: return

        full_lf = (
            pl.concat(lazy_frames, how="diagonal")
            .with_columns(get_dob_age_expressions())
            .filter(
                # FINAL FILTER LOGIC:
                # 1. Calculated Age <= 40
                # 2. Email is non-null and non-empty
                # 3. Mobile is non-null and non-empty
                (pl.col("calculated_age").is_not_null()) &
                (pl.col("calculated_age") <= 40) &
                (pl.col("email").is_not_null()) & (pl.col("email") != "") &
                (pl.col("mobile").is_not_null()) & (pl.col("mobile") != "")
            )
            .unique(subset=["email"], maintain_order=True)
            .unique(subset=["mobile"], maintain_order=True)
        )

        final_csv = self.output_dir / "final_clean.csv"
        db_path = self.output_dir / "leads.db"

        logging.info(f"Sinking cleaned data to {final_csv}...")
        full_lf.collect(engine="streaming").write_csv(final_csv)

        # Persistence to SQLite
        if_exists = "replace" if not db_path.exists() else "append"
        reader = pl.read_csv_batched(final_csv, batch_size=100_000)
        batches = reader.next_batches(1)
        while batches:
            for batch in batches:
                batch.write_database(
                    table_name="leads",
                    connection=f"sqlite:///{db_path}",
                    if_table_exists=if_exists,
                    engine="adbc"
                )
                if_exists = "append"
            batches = reader.next_batches(1)

        with open(self.checkpoint_path, "w") as f: json.dump(csv_files, f)
        logging.info("Pipeline executed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    ProductionLeadsFilter(args.input, args.output).run()
