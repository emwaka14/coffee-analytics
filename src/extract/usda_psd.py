"""
Extract green coffee Production, Supply & Distribution (PSD) data from the
USDA FAS Open Data API for the countries and years in config/settings.py.

Requires USDA_API_KEY in .env — get one free at https://api.data.gov/signup/
then register it at the USDA FAS Open Data portal.

The PSD "by commodity/country/year" endpoint has no "all years" option, so
this loops year by year per country. It also pulls the reference tables
(commodityAttributes, unitsOfMeasure, countries, commodities) once, since
the data rows only contain numeric IDs (attributeId, unitId, countryCode).

Each raw row also carries calendarYear/month — this is *when USDA recorded
that estimate*, not the crop year. The same marketYear gets revised monthly
for years, so this script keeps only the latest (max calendarYear, month)
estimate per (country, marketYear, attributeId) — that's normally what you
want for analysis. The full, unfiltered history is still saved separately
in case you need to look at how estimates changed over time.
"""
import time

import pandas as pd
import requests

from config.settings import (
    USDA_API_KEY, USDA_BASE_URL, USDA_COMMODITY_CODE,
    COUNTRIES, START_YEAR, END_YEAR,
)
from src.extract._utils import save_raw

HEADERS = {"X-Api-Key": USDA_API_KEY, "Accept": "application/json"}
# NOTE: the header name USDA expects has been inconsistent across their own
# docs/domains (API_KEY vs X-Api-Key vs Ocp-Apim-Subscription-Key). If you
# get 401s, check the header name your working requests actually use.

REQUEST_DELAY_SEC = 0.5   # be polite / stay under rate limits
MAX_RETRIES = 3


def _get(path: str, params: dict | None = None) -> list | dict:
    url = f"{USDA_BASE_URL}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = 5 * attempt
            print(f"  Rate limited on {path}, waiting {wait}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue
        print(f"  WARNING: {path} returned HTTP {resp.status_code}: {resp.text[:200]}")
        return []
    print(f"  Giving up on {path} after {MAX_RETRIES} attempts.")
    return []


# ---------------------------------------------------------------- reference
def fetch_reference_tables() -> dict[str, pd.DataFrame]:
    """Pull the lookup tables once so attributeId/unitId become readable."""
    print("Fetching reference tables (attributes, units, countries, commodities)...")
    attrs = pd.DataFrame(_get("/psd/commodityAttributes"))
    units = pd.DataFrame(_get("/psd/unitsOfMeasure"))
    countries = pd.DataFrame(_get("/psd/countries"))
    commodities = pd.DataFrame(_get("/psd/commodities"))

    for name, df in [("attributes", attrs), ("units", units),
                      ("countries", countries), ("commodities", commodities)]:
        if df.empty:
            print(f"  WARNING: reference table '{name}' came back empty — "
                  f"check the endpoint path/response shape and adjust the "
                  f"column names below if USDA's field names differ.")
        else:
            save_raw(df, f"usda_ref_{name}")

    return {"attributes": attrs, "units": units,
            "countries": countries, "commodities": commodities}


# ------------------------------------------------------------------- pull
def fetch_year(country_code: str, market_year: int) -> list[dict]:
    path = f"/psd/commodity/{USDA_COMMODITY_CODE}/country/{country_code}/year/{market_year}"
    data = _get(path)
    time.sleep(REQUEST_DELAY_SEC)
    return data if isinstance(data, list) else []


def run() -> pd.DataFrame:
    if not USDA_API_KEY:
        raise RuntimeError("USDA_API_KEY not set — add it to your .env file.")

    ref = fetch_reference_tables()

    all_records = []
    for country_name, info in COUNTRIES.items():
        code = info["usda_country_code"]
        print(f"Fetching USDA PSD for {country_name} ({code}), "
              f"{START_YEAR}-{END_YEAR}...")
        for year in range(START_YEAR, END_YEAR + 1):
            records = fetch_year(code, year)
            for r in records:
                r["country_name"] = country_name
            all_records.extend(records)
            if not records:
                print(f"  {year}: no data")

    raw_df = pd.DataFrame(all_records)
    if raw_df.empty:
        print("No records returned at all — check API key, base URL, and country/commodity codes.")
        return raw_df

    save_raw(raw_df, "usda_psd_full_history")  # every revision, unfiltered

    # Keep only the latest revision per (country, marketYear, attributeId)
    raw_df["marketYear"] = raw_df["marketYear"].astype(int)
    raw_df["calendarYear"] = raw_df["calendarYear"].astype(int)
    raw_df["month"] = raw_df["month"].astype(int)
    raw_df = raw_df.sort_values(["calendarYear", "month"])
    # drop_duplicates(keep="last") keeps one *whole* row per key. (The old
    # groupby().last() takes the last non-null value per column, which can
    # stitch together fields from different revisions.)
    latest = raw_df.drop_duplicates(
        subset=["country_name", "marketYear", "attributeId"], keep="last"
    )

    # Join in human-readable attribute/unit names if the reference tables came back
    if not ref["attributes"].empty and "attributeId" in ref["attributes"].columns:
        latest = latest.merge(
            ref["attributes"][["attributeId", "attributeName"]],
            on="attributeId", how="left",
        )
    if not ref["units"].empty and "unitId" in ref["units"].columns:
        latest = latest.merge(
            ref["units"][["unitId", "unitDescription"]],
            on="unitId", how="left",
        )
    # NOTE: verify the actual column names (attributeName, unitDescription)
    # against what /psd/commodityAttributes and /psd/unitsOfMeasure return —
    # adjust the column names above to match if USDA labels them differently.

    save_raw(latest, "usda_psd")
    return latest


if __name__ == "__main__":
    run()
