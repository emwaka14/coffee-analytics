"""
Agronomic assumptions used to turn raw weather into coffee-relevant features.

!! These are approximations from general coffee agronomy, NOT validated
!! local calendars. Have an agronomist (or the ICO/national board calendars)
!! confirm them for each country before drawing conclusions.
"""

# ---- weather history & baseline ------------------------------------------
WEATHER_START_DATE = "1991-01-01"   # long enough for a 1991-2020 climatology
BASELINE_START = 1991
BASELINE_END = 2020
MIN_BASELINE_YEARS = 20             # need this many baseline years to compute a z-score

# ---- daily-extreme thresholds ---------------------------------------------
HEAT_THRESHOLD_C = 30.0    # Tmax at/above this: heat stress (mostly Arabica)
FROST_THRESHOLD_C = 2.0    # 2m Tmin at/below this ~ ground frost risk
WET_DAY_MM = 1.0           # a day counts as "dry" below this rainfall
# Robusta lowlands (Dak Lak Tmax often exceeds 30C in the dry season) would trip a
# 30C rule constantly, so use a higher bar there. Judgment call - validate it.
HEAT_THRESHOLD_OVERRIDES = {"Viet Nam": 34.0}

# ---- phenology windows -----------------------------------------------------
# A "crop year" Y = the harvest-start year, same as USDA marketYear.
# Window = (start_year_offset, start_month, end_year_offset, end_month),
# offsets relative to Y (-1 = the year before the harvest year).
NORTHERN_PATTERN = {          # Vietnam, Colombia, Uganda, Ethiopia, Kenya, C. America...
    "flowering": (0, 2, 0, 4),
    "fill":      (0, 5, 0, 10),
}
SOUTHERN_PATTERN = {          # Brazil, Peru...
    "flowering": (-1, 9, -1, 11),
    "fill":      (-1, 12, 0, 4),
}
SOUTHERN_LAT_CUTOFF = -8.0    # countries whose mean region latitude is below this
                              # use SOUTHERN_PATTERN unless overridden below

# Per-country overrides, keyed by the country names used in config.settings.
PHENOLOGY_OVERRIDES = {
    "Brazil": {**SOUTHERN_PATTERN, "frost_season": (0, 6, 0, 8)},
    # Bimodal producers (Colombia, Kenya, Uganda) really have two cycles;
    # add a second window set here once you decide how to model them.
}

# ---- region weights ---------------------------------------------------------
# Initial analytical weights for country-level climate aggregation.
#
# These are coffee-production-share approximations for the first version of
# the regional climate model. They are NOT presented as official regional
# production statistics.
#
# The transformation layer uses these weights to calculate production-weighted
# country climate indicators. Replace these with sourced regional production
# shares when reliable regional production data are integrated.
#
# The weights within each country sum to 1.0.

REGION_WEIGHTS: dict[str, dict[str, float]] = {
    "Brazil": {
        "Sul de Minas": 0.42,
        "Cerrado Mineiro": 0.23,
        "Mogiana (SP)": 0.12,
        "Matas de Minas": 0.08,
        "Espirito Santo (conilon)": 0.15,
    },

    "Viet Nam": {
        "Dak Lak": 0.38,
        "Gia Lai": 0.20,
        "Dak Nong": 0.17,
        "Lam Dong": 0.15,
        "Kon Tum": 0.10,
    },

    "Colombia": {
        "Huila": 0.17,
        "Antioquia": 0.13,
        "Tolima": 0.12,
        "Cauca": 0.11,
        "Caldas": 0.07,
        "Santander": 0.40,
    },

    "Indonesia": {
        "Aceh (Gayo)": 0.18,
        "North Sumatra": 0.18,
        "South Sumatra": 0.20,
        "Lampung": 0.16,
        "Java": 0.12,
        "Sulawesi": 0.16,
    },

    "Ethiopia": {
        "Jimma-Limu": 0.25,
        "Sidama-Yirgacheffe": 0.22,
        "Guji": 0.14,
        "Wollega": 0.15,
        "Kaffa": 0.14,
        "Harar": 0.10,
    },

    "Uganda": {
        "Central": 0.30,
        "East (Mt Elgon)": 0.30,
        "South West": 0.22,
        "West (Rwenzori)": 0.18,
    },

    "India": {
        "Karnataka": 0.70,
        "Kerala": 0.20,
        "Tamil Nadu": 0.08,
        "Andhra Pradesh": 0.02,
    },

    "Honduras": {
        "Copan": 0.22,
        "Montecillos": 0.20,
        "Opalaca": 0.17,
        "Agalta": 0.12,
        "Comayagua": 0.15,
        "El Paraiso": 0.14,
    },

    "Peru": {
        "Cajamarca": 0.25,
        "Junin (Chanchamayo)": 0.30,
        "San Martin": 0.20,
        "Cusco": 0.15,
        "Amazonas": 0.10,
    },

    "Mexico": {
        "Chiapas": 0.40,
        "Veracruz": 0.25,
        "Puebla": 0.15,
        "Oaxaca": 0.12,
        "Guerrero": 0.08,
    },
}
