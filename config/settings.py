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
# 'faostat_name' / 'usda_psd_code' may differ from the common name —
# keep the mapping here so scripts stay dumb and reusable.
COUNTRIES = {
    "Brazil":    {"faostat_name": "Brazil",    "usda_country_code": "BR"},
    "Viet Nam":  {"faostat_name": "Viet Nam",  "usda_country_code": "VM"},
    "Colombia":  {"faostat_name": "Colombia",  "usda_country_code": "CO"},
    "Indonesia": {"faostat_name": "Indonesia", "usda_country_code": "ID"},
    "Ethiopia":  {"faostat_name": "Ethiopia",  "usda_country_code": "ET"},
    "Uganda":    {"faostat_name": "Uganda",    "usda_country_code": "UG"},
    "India":     {"faostat_name": "India",     "usda_country_code": "IN"},
    "Honduras":  {"faostat_name": "Honduras",  "usda_country_code": "HO"},
    "Peru":      {"faostat_name": "Peru",      "usda_country_code": "PE"},
    "Mexico":    {"faostat_name": "Mexico",    "usda_country_code": "MX"},
}

# NOTE: verify usda_country_code values against the PSD country reference
# endpoint before first run — confirm rather than assume these are current.

# ---- growing regions (lat/lon anchor points for weather pulls) ----
REGIONS = {
    "Brazil": {
        "Sul de Minas":            {"lat": -21.50, "lon": -45.00, "elevation": 1000},
        "Cerrado Mineiro":         {"lat": -18.94, "lon": -46.99, "elevation": 950},
        "Mogiana (SP)":            {"lat": -20.54, "lon": -47.40, "elevation": 1000},
        "Matas de Minas":          {"lat": -20.26, "lon": -42.03, "elevation": 850},
        "Espirito Santo (conilon)": {"lat": -19.54, "lon": -40.63, "elevation": 250},
    },

    "Viet Nam": {
        "Dak Lak":   {"lat": 12.67, "lon": 108.04, "elevation": 500},
        "Gia Lai":   {"lat": 13.98, "lon": 108.00, "elevation": 750},
        "Dak Nong":  {"lat": 12.00, "lon": 107.69, "elevation": 600},
        "Lam Dong":  {"lat": 11.94, "lon": 108.44, "elevation": 1400},
        "Kon Tum":   {"lat": 14.35, "lon": 108.00, "elevation": 600},
    },

    "Colombia": {
        "Huila":       {"lat": 2.55, "lon": -75.50, "elevation": 1600},
        "Antioquia":   {"lat": 6.25, "lon": -75.55, "elevation": 1700},
        "Tolima":      {"lat": 4.30, "lon": -75.20, "elevation": 1500},
        "Cauca":       {"lat": 2.45, "lon": -76.60, "elevation": 1700},
        "Caldas":      {"lat": 5.05, "lon": -75.50, "elevation": 1600},
        "Santander":   {"lat": 6.80, "lon": -73.10, "elevation": 1500},
    },

    "Indonesia": {
        "Aceh (Gayo)":     {"lat": 4.60, "lon": 96.80,  "elevation": 1300},
        "North Sumatra":   {"lat": 2.60, "lon": 98.70,  "elevation": 1400},
        "South Sumatra":   {"lat": -4.00, "lon": 104.00, "elevation": 800},
        "Lampung":         {"lat": -5.00, "lon": 105.20, "elevation": 700},
        "Java":            {"lat": -7.00, "lon": 110.00, "elevation": 1100},
        "Sulawesi":        {"lat": -1.50, "lon": 120.00, "elevation": 1200},
    },

    "Ethiopia": {
        "Jimma-Limu":          {"lat": 7.67, "lon": 36.83, "elevation": 1750},
        "Sidama-Yirgacheffe":  {"lat": 6.16, "lon": 38.20, "elevation": 1900},
        "Guji":                {"lat": 5.60, "lon": 38.30, "elevation": 2000},
        "Wollega":             {"lat": 9.10, "lon": 35.80, "elevation": 1900},
        "Kaffa":               {"lat": 7.25, "lon": 36.25, "elevation": 1700},
        "Harar":               {"lat": 9.31, "lon": 42.13, "elevation": 1800},
    },

    "Uganda": {
        "Central":             {"lat": 0.62, "lon": 32.48, "elevation": 1150},
        "East (Mt Elgon)":     {"lat": 1.20, "lon": 34.35, "elevation": 1700},
        "South West":          {"lat": -1.29, "lon": 29.75, "elevation": 1800},
        "West (Rwenzori)":     {"lat": 0.45, "lon": 30.00, "elevation": 1500},
    },

    "India": {
        "Karnataka":           {"lat": 12.30, "lon": 75.80, "elevation": 1100},
        "Kerala":              {"lat": 11.50, "lon": 76.10, "elevation": 900},
        "Tamil Nadu":          {"lat": 11.40, "lon": 77.00, "elevation": 1200},
        "Andhra Pradesh":      {"lat": 14.00, "lon": 78.50, "elevation": 800},
    },

    "Honduras": {
        "Copan":               {"lat": 14.85, "lon": -89.15, "elevation": 1300},
        "Montecillos":         {"lat": 14.10, "lon": -88.10, "elevation": 1400},
        "Opalaca":             {"lat": 14.80, "lon": -88.40, "elevation": 1400},
        "Agalta":              {"lat": 15.20, "lon": -86.50, "elevation": 1200},
        "Comayagua":           {"lat": 14.50, "lon": -87.65, "elevation": 1200},
        "El Paraiso":          {"lat": 13.85, "lon": -86.55, "elevation": 1300},
    },

    "Peru": {
        "Cajamarca":           {"lat": -6.90, "lon": -78.50, "elevation": 1800},
        "Junin (Chanchamayo)": {"lat": -11.05, "lon": -75.30, "elevation": 1300},
        "San Martin":          {"lat": -7.00, "lon": -76.50, "elevation": 1000},
        "Cusco":               {"lat": -13.50, "lon": -71.95, "elevation": 1800},
        "Amazonas":            {"lat": -6.20, "lon": -78.00, "elevation": 1700},
    },

    "Mexico": {
        "Chiapas":             {"lat": 15.10, "lon": -92.60, "elevation": 1200},
        "Veracruz":            {"lat": 19.50, "lon": -96.90, "elevation": 1100},
        "Puebla":              {"lat": 19.00, "lon": -97.80, "elevation": 1300},
        "Oaxaca":              {"lat": 17.10, "lon": -96.70, "elevation": 1300},
        "Guerrero":            {"lat": 17.70, "lon": -99.90, "elevation": 1100},
    },
}
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
START_YEAR = 2000
END_YEAR = 2026
START_DATE = f"{START_YEAR}-01-01"

# End date to be at most a day ago
if END_YEAR == date.today().year:
    END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
else:
    END_DATE = f"{END_YEAR}-12-31"

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
