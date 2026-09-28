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
# Share of the country's coffee production per region, e.g.
# REGION_WEIGHTS = {"Brazil": {"Sul de Minas": 0.5, "Cerrado Mineiro": 0.3, "Espirito Santo": 0.2}}
# Countries not listed get equal weights (a fallback, not a recommendation).
# Better still: weight by coffee-area from a gridded map such as MapSPAM.
REGION_WEIGHTS: dict[str, dict[str, float]] = {}
