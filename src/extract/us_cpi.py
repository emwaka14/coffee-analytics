"""
US consumer price index (annual average), used to deflate nominal USD prices.

Uses FRED (series CPIAUCSL) when FRED_API_KEY is set - it is more current -
otherwise falls back to the keyless World Bank series FP.CPI.TOTL, which lags
by a year or more. Response shapes weren't verified against live calls while
writing this; if either errors, print resp.json() and adjust the parser.
The current year's FRED value is a partial-year average; the transform step
ignores it when choosing the base year.
"""
import pandas as pd
import requests

from config.settings import FRED_API_KEY
from src.extract._utils import save_raw

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
WB_URL = "https://api.worldbank.org/v2/country/USA/indicator/FP.CPI.TOTL?format=json&per_page=200"


def _fred() -> pd.DataFrame:
    resp = requests.get(FRED_URL, params={
        "series_id": "CPIAUCSL", "api_key": FRED_API_KEY, "file_type": "json",
        "frequency": "a", "aggregation_method": "avg",
    }, timeout=60)
    resp.raise_for_status()
    rows = [{"year": int(o["date"][:4]), "cpi": float(o["value"])}
            for o in resp.json()["observations"] if o["value"] != "."]
    return pd.DataFrame(rows)


def _world_bank() -> pd.DataFrame:
    resp = requests.get(WB_URL, timeout=60)
    resp.raise_for_status()
    return pd.DataFrame([{"year": int(r["date"]), "cpi": r["value"]}
                         for r in resp.json()[1] if r["value"] is not None])


def run() -> pd.DataFrame:
    df = _fred() if FRED_API_KEY else _world_bank()
    df = df.sort_values("year").reset_index(drop=True)
    save_raw(df, "us_cpi")
    return df


if __name__ == "__main__":
    run()
