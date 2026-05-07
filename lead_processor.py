import polars as pl
import os
import re
import dns.resolver
import sqlite3
from datetime import datetime

# 1. Configuration & Column Mapping
FILE_PATHS = ["leads_1.csv", "leads_2.xlsx"]  # To be populated with actual file paths

# Define Aliases for robust mapping
# These are the columns used for internal filtering logic
ALIASES = {
    "email": ["email", "email address", "e-mail", "email_1", "contact email", "primary email"],
    "mobile": ["mobile", "phone", "cell", "contact number", "mobile number", "phone number", "primary phone"],
    "dob": ["dob", "date of birth", "birth date", "birthdate", "age", "birthday", "date_of_birth"]
}

# Internal consistent column names
L_EMAIL = "email"
L_MOBILE = "mobile"
L_DOB = "dob"

def load_data(file_paths):
    lazy_frames = []
    for path in file_paths:
        if not os.path.exists(path):
            print(f"File not found: {path}")
            continue

        try:
            print(f"Attempting to load {path}...")
            if path.endswith('.csv'):
                lf = pl.scan_csv(path, infer_schema_length=10000)
            elif path.endswith(('.xlsx', '.xls')):
                df = pl.read_excel(path, engine='calamine')
                lf = df.lazy()
            else:
                print(f"Unsupported file format: {path}")
                continue

            # 1. Normalize ALL existing column names (strip spaces, lowercase)
            # This ensures we can match them easily while keeping ALL data
            current_cols = lf.collect_schema().names()
            normalized_map = {c: c.strip().lower() for c in current_cols}
            lf = lf.rename(normalized_map)

            normalized_cols = list(normalized_map.values())

            # 2. Map aliases to our internal processing names (email, mobile, dob)
            final_map = {}
            for internal, alias_list in ALIASES.items():
                found_col = next((c for c in alias_list if c in normalized_cols), None)
                if found_col:
                    # If the column already has the internal name, rename is a no-op
                    final_map[found_col] = internal
                else:
                    print(f"Warning: Could not find a match for '{internal}' in {path}")

            # 3. Validate mandatory columns (email, mobile)
            if L_EMAIL not in final_map.values() or L_MOBILE not in final_map.values():
                print(f"Skipping {path}: Missing mandatory columns (Email/Mobile).")
                print(f"Found headers: {normalized_cols}")
                continue

            # Apply the mapping (renames target columns to internal names)
            lf = lf.rename(final_map)

            # 4. Handle missing DOB column
            if L_DOB not in lf.collect_schema().names():
                print(f"Warning: DOB column missing in {path}. Adding empty DOB column.")
                lf = lf.with_columns(pl.lit(None).alias(L_DOB))

            lazy_frames.append(lf)
            print(f"Successfully loaded {path} with {len(normalized_cols)} columns.")
        except Exception as e:
            print(f"Error loading {path}: {e}")

    if not lazy_frames:
        return None

    # Use diagonal concatenation to handle different columns in different files
    return pl.concat(lazy_frames, how="diagonal")

def filter_age(lf):
    current_year = datetime.now().year

    # Handle DOB formats like 'MM/DD/YYYY', 'YYYY-MM-DD', or just 'YYYY'
    # We extract the first sequence of 4 digits which represents the year in these formats
    lf = lf.with_columns(
        pl.col(L_DOB).cast(pl.String).str.extract(r"(\d{4})").cast(pl.Int32).alias("birth_year")
    )

    # Filter: Keep if age <= 40.
    # NOTE: We keep rows where birth_year is null to avoid dropping 100% of data
    # if the column was missing or unparseable.
    lf = lf.filter(
        pl.col("birth_year").is_null() | ((current_year - pl.col("birth_year")) <= 40)
    ).drop("birth_year")

    return lf

def filter_emails(lf):
    # Strict email regex
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

    lf = lf.filter(
        pl.col(L_EMAIL).str.contains(email_regex)
    )

    return lf

def clean_mobile(lf):
    # Strip symbols (+, -, spaces)
    lf = lf.with_columns(
        pl.col(L_MOBILE).cast(pl.String).str.replace_all(r"[\+\-\s]", "")
    )

    # Strip country code '91' or '1' if it starts with it and has 12/11 digits
    # If starts with 91 and length is 12, strip 91. If starts with 1 and length is 11, strip 1.
    lf = lf.with_columns(
        pl.when(pl.col(L_MOBILE).str.starts_with("91") & (pl.col(L_MOBILE).str.len_chars() == 12))
        .then(pl.col(L_MOBILE).str.slice(2))
        .when(pl.col(L_MOBILE).str.starts_with("1") & (pl.col(L_MOBILE).str.len_chars() == 11))
        .then(pl.col(L_MOBILE).str.slice(1))
        .otherwise(pl.col(L_MOBILE))
        .alias(L_MOBILE)
    )

    # Keep only 10 digits
    lf = lf.filter(
        pl.col(L_MOBILE).str.contains(r"^\d{10}$")
    )

    return lf

def validate_mx(lf):
    # Extract domains
    lf = lf.with_columns(
        pl.col(L_EMAIL).str.split("@").list.get(1).alias("domain")
    )

    # Get unique domains
    # Note: To get unique domains we need to collect or at least partially collect.
    # However, we can use a join with a small dataframe of valid domains.

    print("Extracting unique domains for MX validation...")
    unique_domains_df = lf.select("domain").unique().collect()
    unique_domains = unique_domains_df.get_column("domain").to_list()

    valid_domains = []
    print(f"Checking {len(unique_domains)} unique domains...")

    # Use a cache to avoid re-checking domains
    mx_cache = {}

    for domain in unique_domains:
        if domain in mx_cache:
            if mx_cache[domain]:
                valid_domains.append(domain)
            continue

        try:
            # Short timeout for performance
            dns.resolver.resolve(domain, 'MX', lifetime=2)
            valid_domains.append(domain)
            mx_cache[domain] = True
        except Exception:
            mx_cache[domain] = False

    print(f"Found {len(valid_domains)} valid domains.")

    # Filter main dataset
    valid_domains_df = pl.DataFrame({"domain": valid_domains}, schema={"domain": pl.String}).lazy()
    lf = lf.join(valid_domains_df, on="domain", how="inner").drop("domain")

    return lf

def save_to_sqlite(df, db_path="cleaned_leads.db"):
    print(f"Saving to SQLite: {db_path}")
    conn = sqlite3.connect(db_path)
    # Convert polars dataframe to pandas for easy sqlite export if needed,
    # but polars has write_database if connectorx or adbc is installed.
    # Here we'll use a simple manual insert or pandas.
    try:
        import pandas as pd
        df.to_pandas().to_sql("leads", conn, if_exists="replace", index=False)

        # Create indexes
        cursor = conn.cursor()
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_email ON leads({L_EMAIL})")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_mobile ON leads({L_MOBILE})")
        conn.commit()
    except ImportError:
        # Fallback if pandas not available (though it should be)
        print("Pandas not found, using manual insert for SQLite...")
        cursor = conn.cursor()
        cols = df.columns
        cursor.execute(f"CREATE TABLE IF NOT EXISTS leads ({', '.join([f'{c} TEXT' for c in cols])})")
        for row in df.iter_rows():
            cursor.execute(f"INSERT INTO leads VALUES ({', '.join(['?' for _ in cols])})", row)

        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_email ON leads({L_EMAIL})")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_mobile ON leads({L_MOBILE})")
        conn.commit()
    finally:
        conn.close()

def export_to_excel(df, chunk_size=1000000, prefix="cleaned_leads"):
    num_rows = df.height
    num_chunks = (num_rows // chunk_size) + (1 if num_rows % chunk_size > 0 else 0)

    print(f"Exporting {num_rows} rows to {num_chunks} Excel file(s)...")

    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, num_rows)
        chunk = df.slice(start, end - start)

        file_name = f"{prefix}_part_{i+1}.xlsx"
        print(f"Writing {file_name}...")
        # Polars write_excel
        chunk.write_excel(file_name)

def main():
    print("Starting lead processing...")
    lf = load_data(FILE_PATHS)
    if lf is None:
        print("No data loaded.")
        return

    print("Filtering by age...")
    lf = filter_age(lf)

    print("Validating emails...")
    lf = filter_emails(lf)

    print("Cleaning mobile numbers...")
    lf = clean_mobile(lf)

    print("Performing MX validation...")
    lf = validate_mx(lf)

    print("Collecting results (streaming)...")
    final_df = lf.collect(engine="streaming")

    if final_df.height == 0:
        print("No results after filtering.")
        return

    save_to_sqlite(final_df)
    export_to_excel(final_df)

if __name__ == "__main__":
    main()
