"""
Load data into your Aiven (or any) Postgres instance.

Ownership of tables:
  schema.sql owns  dim_country, dim_attribute, dim_unit, fact_psd_annual,
                   fact_weather_monthly, fact_weather_region_window,
                   seasonal_outlook          (CREATE IF NOT EXISTS; applied here
                                              on every run, so it is idempotent)
  this script owns coffee_country_year       (~100 evolving columns; rebuilt from
                                              the CSV each run, then a PK is added)

SAFETY (why a reload can't leave you with an empty database):
  - The whole reload (schema, view drop, truncates, inserts, view creation) runs in ONE
    transaction. If anything fails it rolls back and the database is exactly as before.
    Dashboards read the old data until the commit (they can block for the few seconds
    the reload holds its locks).
  - A table is only truncated/replaced if its source file exists. A run that lacks, say,
    the weather CSV leaves the weather tables untouched instead of emptying them.

Load behaviour:
  - dims / fact_psd_annual / weather tables: TRUNCATE + re-insert. Never dropped,
    so foreign keys survive (a plain to_sql(if_exists="replace") would fail with
    DependentObjectsStillExist on the dims).
  - seasonal_outlook: APPEND-ONLY by issue_date (history is never truncated).
    Every dated raw file is backfilled, so skipped runs aren't lost.
  - coffee_country_year: dropped and recreated each load.
  - Dashboard views (sql/views.sql, mv_*): dropped BEFORE the tables are rebuilt and
    recreated at the end, so they can never block a reload.

CLI:
  python -m src.load.to_postgres             full reload + views
  python -m src.load.to_postgres --refresh   only REFRESH the views (no reload)
"""
import glob
import re
import sys

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from config.settings import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE,
    RAW_DIR, PROCESSED_DIR, ROOT_DIR, PSD_ATTRIBUTE_MAP,
)

SCHEMA_PATH = ROOT_DIR / "sql" / "schema.sql"
VIEWS_PATH = ROOT_DIR / "sql" / "views.sql"
DROP_VIEWS_PATH = ROOT_DIR / "sql" / "drop_views.sql"

# Creation order matters: mv_weather_monthly_anomaly reads mv_weather_climatology.
MV_ORDER = ["mv_country_year", "mv_country_snapshot", "mv_weather_climatology",
            "mv_weather_monthly_anomaly", "mv_phase_anomaly",
            "mv_seasonal_outlook_latest", "mv_data_quality"]

SEASONAL_DDL = """
CREATE TABLE IF NOT EXISTS seasonal_outlook (
    country_name TEXT NOT NULL, region TEXT NOT NULL,
    issue_date DATE NOT NULL, time DATE NOT NULL,
    temperature_2m_mean NUMERIC, temperature_2m_anomaly NUMERIC,
    precipitation_mean NUMERIC, precipitation_anomaly NUMERIC,
    loaded_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (country_name, region, issue_date, time)
)"""


# ------------------------------------------------------------------ plumbing
def get_engine():
    # URL.create escapes special characters in the password (an f-string URL breaks on '@', '/', '#').
    url = URL.create(
        "postgresql+psycopg2", username=DB_USER, password=DB_PASSWORD,
        host=DB_HOST, port=int(DB_PORT), database=DB_NAME,
        query={"sslmode": DB_SSLMODE},
    )
    return create_engine(url)


def apply_schema(conn):
    conn.exec_driver_sql(SCHEMA_PATH.read_text())
    print(f"  Applied {SCHEMA_PATH.name} (CREATE IF NOT EXISTS - existing tables untouched).")


def run_sql_file(conn, path, label: str):
    """Run a .sql file statement by statement so one failure names its statement
    instead of hiding the rest. Each statement gets a SAVEPOINT, so a failing view rolls
    back on its own without aborting the surrounding reload transaction.
    Statements are split on ';' (keep comments free of them)."""
    body = "\n".join(l for l in path.read_text().splitlines() if not l.strip().startswith("--"))
    ok = failed = 0
    for stmt in filter(None, (s.strip() for s in body.split(";"))):
        try:
            with conn.begin_nested():
                conn.exec_driver_sql(stmt)
            ok += 1
        except Exception as e:
            failed += 1
            head = re.sub(r"\s+", " ", stmt)[:70]
            print(f"  {label} FAILED: {head}...\n    {str(e.orig if hasattr(e, 'orig') else e).strip()[:200]}")
    print(f"  {label}: {ok} statements ok" + (f", {failed} FAILED" if failed else ""))


def drop_views(conn):
    run_sql_file(conn, DROP_VIEWS_PATH, "drop views")


def create_views(conn):
    run_sql_file(conn, VIEWS_PATH, "create views")


def refresh_views(engine):
    """Refresh only (no reload). Use after a new seasonal outlook pull."""
    for name in MV_ORDER:
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"REFRESH MATERIALIZED VIEW {name}")
            print(f"  refreshed {name}")
        except Exception as e:
            print(f"  could not refresh {name}: {str(e.orig if hasattr(e, 'orig') else e).strip()[:150]}")


def truncate(conn, table_name: str, cascade: bool = False):
    suffix = " CASCADE" if cascade else ""
    conn.execute(text(f"TRUNCATE TABLE {table_name}{suffix}"))


def _append(conn, df: pd.DataFrame, table: str):
    """Append only the columns the table actually has; say so if any are dropped."""
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    extra = [c for c in df.columns if c not in cols]
    if extra:
        print(f"  NOTE: {table} has no column(s) {extra} - not loaded. "
              f"Add them to schema.sql if you want them.")
    df[[c for c in df.columns if c in cols]].to_sql(table, conn, if_exists="append", index=False)


def _clean_ref(df, rename, keep, key):
    df = df.rename(columns=rename)[keep].drop_duplicates()
    before = len(df)
    df = df.dropna(subset=[key])
    if len(df) < before:
        print(f"  Dropped {before - len(df)} rows with no {key}.")
    return df


# ---------------------------------------------------------------------- dims
def load_dim_country(conn):
    path = RAW_DIR / "usda_ref_countries_latest.csv"
    if not path.exists():
        print("  Skipping dim_country - reference file not found.")
        return
    df = _clean_ref(pd.read_csv(path), {"countryCode": "country_code", "countryName": "country_name"},
                    ["country_code", "country_name"], "country_code")
    _append(conn, df, "dim_country")
    print(f"  dim_country: {len(df):,} rows")


def load_dim_attribute(conn):
    path = RAW_DIR / "usda_ref_attributes_latest.csv"
    if not path.exists():
        print("  Skipping dim_attribute - reference file not found.")
        return
    df = pd.read_csv(path).rename(columns={"attributeId": "attribute_id", "attributeName": "attribute_name"})
    # schema.sql documents short_name as the PSD_ATTRIBUTE_MAP name - populate it.
    df["short_name"] = df["attribute_name"].map(PSD_ATTRIBUTE_MAP)
    df = df[["attribute_id", "attribute_name", "short_name"]].drop_duplicates("attribute_id")
    df = df.dropna(subset=["attribute_id"])
    unmapped = set(PSD_ATTRIBUTE_MAP) - set(df["attribute_name"])
    if unmapped:
        print(f"  WARNING: PSD_ATTRIBUTE_MAP names not found in USDA's attribute list "
              f"(they'll silently produce no column): {sorted(unmapped)}")
    _append(conn, df, "dim_attribute")
    print(f"  dim_attribute: {len(df):,} rows")


def load_dim_unit(conn):
    path = RAW_DIR / "usda_ref_units_latest.csv"
    if not path.exists():
        print("  Skipping dim_unit - reference file not found.")
        return
    df = _clean_ref(pd.read_csv(path), {"unitId": "unit_id", "unitDescription": "unit_name"},
                    ["unit_id", "unit_name"], "unit_id")
    _append(conn, df, "dim_unit")
    print(f"  dim_unit: {len(df):,} rows")


# ---------------------------------------------------------------------- facts
def load_fact_psd(conn):
    path = RAW_DIR / "usda_psd_latest.csv"
    if not path.exists():
        print("  Skipping fact_psd_annual - usda_psd_latest.csv not found.")
        return
    df = pd.read_csv(path).rename(columns={
        "countryCode": "country_code", "marketYear": "market_year",
        "attributeId": "attribute_id", "unitId": "unit_id", "calendarYear": "calendar_year",
    })
    keep = ["country_code", "market_year", "attribute_id", "unit_id",
            "value", "calendar_year", "month"]
    df = df[[c for c in keep if c in df.columns]]
    before = len(df)
    df = df.dropna(subset=["country_code", "market_year", "attribute_id"])
    if len(df) < before:
        print(f"  Dropped {before - len(df)} rows missing a key field.")
    _append(conn, df, "fact_psd_annual")
    print(f"  fact_psd_annual: {len(df):,} rows")


def load_weather_monthly(conn):
    path = RAW_DIR / "open_meteo_weather_monthly_latest.csv"
    if not path.exists():
        print("  Skipping fact_weather_monthly - run src.extract.open_meteo first.")
        return
    df = pd.read_csv(path).rename(columns={"Year": "year"})
    _append(conn, df, "fact_weather_monthly")
    print(f"  fact_weather_monthly: {len(df):,} rows")


def load_weather_windows(conn):
    path = PROCESSED_DIR / "weather_region_window_features.csv"
    if not path.exists():
        print("  Skipping fact_weather_region_window - run the transform step first.")
        return
    # 'window' is a reserved word in Postgres; the column is called 'phase'.
    df = pd.read_csv(path).rename(columns={"window": "phase"})
    _append(conn, df, "fact_weather_region_window")
    print(f"  fact_weather_region_window: {len(df):,} rows")


def load_metrics_table(conn):
    path = PROCESSED_DIR / "coffee_country_year.csv"
    if not path.exists():
        print("  Skipping coffee_country_year - run the transform step first.")
        return
    df = pd.read_csv(path)
    df.to_sql("coffee_country_year", conn, if_exists="replace", index=False)
    conn.execute(text("ALTER TABLE coffee_country_year ADD PRIMARY KEY (country, year)"))
    print(f"  coffee_country_year: {len(df):,} rows, {len(df.columns)} columns")


def load_seasonal_outlook(conn):
    """Append-only history keyed by issue_date; backfills from every dated raw file."""
    files = sorted(glob.glob(str(RAW_DIR / "open_meteo_seasonal_outlook_*Z.csv")))
    frames = []
    for f in files:
        d = pd.read_csv(f)
        if "issue_date" in d.columns:          # files from before issue_date existed are skipped
            frames.append(d)
    if not frames:
        print("  Skipping seasonal_outlook - no raw pulls with an issue_date yet.")
        return
    df = pd.concat(frames, ignore_index=True)
    df["issue_date"] = pd.to_datetime(df["issue_date"]).dt.date
    df["time"] = pd.to_datetime(df["time"]).dt.date
    df = df.drop_duplicates(["country_name", "region", "issue_date", "time"], keep="last")

    insp = inspect(conn)
    if insp.has_table("seasonal_outlook"):
        cols = [c["name"] for c in insp.get_columns("seasonal_outlook")]
        if "issue_date" not in cols:
            print("  Legacy seasonal_outlook (no issue_date) - dropping it once and recreating.")
            conn.execute(text("DROP TABLE seasonal_outlook"))
            conn.execute(text(SEASONAL_DDL))
    else:
        conn.execute(text(SEASONAL_DDL))
    for d in df["issue_date"].unique():         # idempotent per issue date
        conn.execute(text("DELETE FROM seasonal_outlook WHERE issue_date = :d"), {"d": d})
    _append(conn, df, "seasonal_outlook")
    print(f"  seasonal_outlook: {len(df):,} rows across {df['issue_date'].nunique()} issue date(s)")


# ---------------------------------------------------------------------- run
def run():
    engine = get_engine()
    with engine.connect() as c:
        c.execute(text("SELECT 1"))  # fail fast if credentials are wrong
    print("Connected. Reloading inside ONE transaction (a failure rolls everything back).")

    usda_files = [RAW_DIR / f"usda_ref_{n}_latest.csv" for n in ("countries", "attributes", "units")]
    usda_files.append(RAW_DIR / "usda_psd_latest.csv")
    can_usda = all(f.exists() for f in usda_files)
    can_weather = (RAW_DIR / "open_meteo_weather_monthly_latest.csv").exists()
    can_windows = (PROCESSED_DIR / "weather_region_window_features.csv").exists()
    for label, ok in (("USDA dims + fact_psd_annual", can_usda), ("fact_weather_monthly", can_weather),
                      ("fact_weather_region_window", can_windows)):
        if not ok:
            print(f"  NOTE: source file(s) missing - {label} left untouched (not truncated).")

    with engine.begin() as conn:       # commits on success, rolls back on any exception
        apply_schema(conn)
        # Views depend on tables that are dropped/rebuilt below, so drop them first.
        drop_views(conn)

        print("Truncating (fact/child tables first, respecting FKs)...")
        if can_usda:
            truncate(conn, "fact_psd_annual")
            truncate(conn, "dim_country", cascade=True)
            truncate(conn, "dim_attribute", cascade=True)
            truncate(conn, "dim_unit", cascade=True)
        if can_weather:
            truncate(conn, "fact_weather_monthly")
        if can_windows:
            truncate(conn, "fact_weather_region_window")
        # seasonal_outlook is deliberately NOT truncated - it accumulates by issue_date.

        print("Loading tables...")
        if can_usda:
            load_dim_country(conn)
            load_dim_attribute(conn)
            load_dim_unit(conn)
            load_fact_psd(conn)
        if can_weather:
            load_weather_monthly(conn)
        if can_windows:
            load_weather_windows(conn)
        load_metrics_table(conn)
        load_seasonal_outlook(conn)
        print("Creating dashboard views...")
        create_views(conn)
    print("Committed. Done.")


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh_views(get_engine())
    else:
        run()
