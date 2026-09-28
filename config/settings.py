"""
Central place for anything an extract/transform script needs to know.
Add new countries, regions, or date ranges here — never hardcode them
inside a script in src/.
"""
import os
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# ---- paths ----
ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

# ---- countries in scope ----
# 'faostat_name' / 'usda_country_code' may differ from the common name —
# keep the mapping here so scripts stay dumb and reusable.
COUNTRIES = {
    "Uganda":   {"faostat_name": "Uganda",   "usda_country_code": "UG"},
    "Ethiopia": {"faostat_name": "Ethiopia", "usda_country_code": "ET"},
    "Brazil":   {"faostat_name": "Brazil",   "usda_country_code": "BR"},
    "Viet Nam": {"faostat_name": "Viet Nam", "usda_country_code": "VM"},
}
# NOTE: verify usda_country_code values against the PSD country reference
# endpoint before first run — confirm rather than assume these are current.

# ---- growing regions (lat/lon anchor points for weather pulls) ----
REGIONS = {
    "Uganda": {
        # South West: point is near Kisoro; fine for the SW arabica/robusta zone.
        "South West": {"lat": -1.29, "lon": 29.75, "elevation": 1800},
        # East: the ORIGINAL point (1.13, 34.53) is the Mount Elgon SUMMIT (~4,300 m).
        # Coffee grows on the Bugisu slopes (Mbale/Sironko/Bulambuli, ~1,300-2,200 m),
        # so the point was moved to the belt (approximate - verify) and elevation given.
        "East":       {"lat": 1.20, "lon": 34.35, "elevation": 1700},
        "Central":    {"lat": 0.62, "lon": 32.48, "elevation": 1150},   # central robusta belt
    },
    "Ethiopia": {
        "Jimma":       {"lat": 7.67, "lon": 36.83, "elevation": 1750},
        "Yirgacheffe": {"lat": 6.16, "lon": 38.20, "elevation": 1900},
        "Bensa":       {"lat": 6.72, "lon": 38.60, "elevation": 2000},
        # Missing: Harar (east) and Limu/Wollega (west) - consider adding.
    },
    "Brazil": {
        # ONE region cannot stand in for Brazil. Added the other major zones
        # (approximate town centroids - verify, and set REGION_WEIGHTS from CONAB
        # production data in config/agronomy.py).
        "Sul de Minas":     {"lat": -21.50, "lon": -45.00, "elevation": 1000},
        "Cerrado Mineiro":  {"lat": -18.94, "lon": -46.99, "elevation": 950},
        "Mogiana (SP)":     {"lat": -20.54, "lon": -47.40, "elevation": 1000},
        "Matas de Minas":   {"lat": -20.26, "lon": -42.03, "elevation": 850},
        "Espirito Santo (conilon)": {"lat": -19.54, "lon": -40.63},   # low-altitude robusta
    },
    "Viet Nam": {
        # Dak Lak alone is roughly a third of national robusta; add the rest of the
        # Central Highlands (approximate town centroids - verify).
        "Dak Lak":  {"lat": 12.67, "lon": 108.04, "elevation": 500},
        "Gia Lai":  {"lat": 13.98, "lon": 108.00, "elevation": 750},
        "Dak Nong": {"lat": 12.00, "lon": 107.69, "elevation": 600},
        "Lam Dong": {"lat": 11.94, "lon": 108.44, "elevation": 1400},   # incl. arabica
    },
}
# Optional "elevation" (metres) makes Open-Meteo downscale temperature to the
# farms' altitude instead of the grid-cell average. Values are rough - refine them.
# NOTE: coordinates above are approximate district/zone centroids, not
# precise farm locations. Good enough for regional climate signal, not
# for anything requiring survey-grade geolocation.

# ---- commodity / item identifiers ----
FAOSTAT_ITEM = "Coffee, green"
USDA_COMMODITY_CODE = "0711100"  # green coffee — verify against PSD commodity list

# ---- PSD attribute -> short column name mapping ----
# Verify these attributeName strings exactly match what your
# /psd/commodityAttributes reference table returns (data/raw/usda_ref_attributes_latest.csv)
# before relying on this — USDA's exact label text/spelling can vary.
PSD_ATTRIBUTE_MAP = {
    "Beginning Stocks": "beginning_stocks",
    "Production": "production",
    "Arabica Production": "arabica_production",
    "Robusta Production": "robusta_production",
    "Other Production": "other_production",
    "Imports": "imports",
    "Bean Imports": "bean_imports",
    "Roast & Ground Imports": "rg_imports",
    "Soluble Imports": "soluble_imports",
    "Total Supply": "total_supply",
    "Exports": "exports",
    "Bean Exports": "bean_exports",
    "Roast & Ground Exports": "rg_exports",
    "Soluble Exports": "soluble_exports",
    "Domestic Consumption": "domestic_consumption",
    "Rst,Ground Dom. Consum": "rg_domestic_consumption",
    "Soluble Dom. Cons.": "soluble_domestic_consumption",
    "Ending Stocks": "ending_stocks",
    "Total Distribution": "total_distribution",
}

# ---- date range ----
# 1993, not 2000: more years = more statistical power for the climate analysis
# (25 yrs x 4 countries is thin), and FAOSTAT lists Ethiopia as 'Ethiopia PDR'
# before 1993, so 1993 is the earliest clean start for the name mapping.
START_YEAR = 1993
# NOTE: the current crop year (2026) is a USDA *forecast* and the weather windows for it
# are incomplete; the pipeline flags it (usda_is_forecast). Set END_YEAR = 2025 for actuals only.
END_YEAR = 2026
START_DATE = f"{START_YEAR}-01-01"

# Open-Meteo's archive lags real time by several days (ERA5), so stop a week short.
# (Partial months at the end are flagged incomplete downstream either way.)
# min() also stops END_YEAR in the future from producing a future end date.
END_DATE = min(date(END_YEAR, 12, 31), date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

# ---- API keys (from .env) ----
USDA_API_KEY = os.getenv("USDA_API_KEY")

# USDA base URL — verify which domain is live for your key.
# Some docs reference apps.fas.usda.gov/OpenData/api, but api.fas.usda.gov/api
# is what has been responding in practice. Override in .env if it changes again.
USDA_BASE_URL = os.getenv("USDA_BASE_URL", "https://api.fas.usda.gov/api")
FRED_API_KEY = os.getenv("FRED_API_KEY")
COMTRADE_API_KEY = os.getenv("COMTRADE_API_KEY")

# ---- Postgres ----
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "coffee_analytics")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
# Aiven needs "require"; a local Postgres without SSL needs "prefer" or "disable".
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
