-- Star-schema-ish design: small dimension tables + one long fact table
-- (source of truth) + one wide, pre-computed metrics table (what the
-- dashboard actually queries — fast, no joins needed at render time).

-- ---------------------------------------------------------------- dims
CREATE TABLE IF NOT EXISTS dim_country (
    country_code   TEXT PRIMARY KEY,   -- e.g. 'UG'
    country_name   TEXT NOT NULL       -- e.g. 'Uganda'
);

CREATE TABLE IF NOT EXISTS dim_attribute (
    attribute_id   INTEGER PRIMARY KEY,
    attribute_name TEXT NOT NULL,      -- e.g. 'Arabica Production'
    short_name     TEXT                -- e.g. 'arabica_production' (matches PSD_ATTRIBUTE_MAP)
);

CREATE TABLE IF NOT EXISTS dim_unit (
    unit_id        INTEGER PRIMARY KEY,
    unit_name      TEXT NOT NULL       -- e.g. '(1000 60 KG BAGS)'
);

-- ---------------------------------------------------------- fact table
-- Long format, one row per (country, market year, attribute) — the
-- latest USDA revision only (see src/extract/usda_psd.py). This is your
-- source of truth; the wide table below is derived from it.
CREATE TABLE IF NOT EXISTS fact_psd_annual (
    country_code   TEXT REFERENCES dim_country(country_code),
    market_year    INTEGER NOT NULL,
    attribute_id   INTEGER REFERENCES dim_attribute(attribute_id),
    unit_id        INTEGER REFERENCES dim_unit(unit_id),
    value          NUMERIC,
    calendar_year  INTEGER,   -- when USDA published this estimate
    month          INTEGER,   -- which monthly/semi-annual release
    loaded_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (country_code, market_year, attribute_id)
);

-- ------------------------------------------------------- metrics table
-- coffee_country_year is NOT defined here any more. It has ~100 columns (every
-- PSD attribute, FAO fields and quality flags, weather-window features, derived
-- metrics) that change whenever a feature is added, so src/load/to_postgres.py
-- rebuilds it from the CSV each run and then adds PRIMARY KEY (country, year).
-- Consequence: a view/dashboard object that depends on it must be recreated
-- after each load. (Point BI tools at it directly, or at a view you re-create.)

-- ------------------------------------------------------------- weather
-- Region x month, straight from the extract. Aggregate late, in queries/analysis.
CREATE TABLE IF NOT EXISTS fact_weather_monthly (
    country_name      TEXT    NOT NULL,
    region            TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    month             INTEGER NOT NULL,
    lat               NUMERIC,
    lon               NUMERIC,
    elevation_m       NUMERIC,   -- downscaling elevation, if one was configured
    temp_mean_c       NUMERIC,
    tmax_mean_c       NUMERIC,
    tmin_mean_c       NUMERIC,
    tmin_abs_c        NUMERIC,
    rain_mm           NUMERIC,
    wet_days          INTEGER,
    max_dry_spell_d   INTEGER,   -- longest dry run inside the month
    heat_days         INTEGER,   -- days with Tmax >= heat_threshold_c
    heat_threshold_c  NUMERIC,
    frost_days        INTEGER,   -- days with Tmin <= 2C
    n_days            INTEGER,
    complete          BOOLEAN,   -- false for a partial (latest) month
    loaded_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (country_name, region, year, month)
);

-- Region x phenology phase x crop year (crop year = USDA marketYear).
-- *_z = z-score vs that region's own 1991-2020 baseline for that phase.
CREATE TABLE IF NOT EXISTS fact_weather_region_window (
    country_name  TEXT    NOT NULL,
    region        TEXT    NOT NULL,
    phase         TEXT    NOT NULL,   -- flowering / fill / frost_season
    crop_year     INTEGER NOT NULL,
    rain_mm       NUMERIC,
    tmean_c       NUMERIC,
    heat_days     NUMERIC,
    frost_days    NUMERIC,
    dry_spell_d   NUMERIC,
    rain_mm_z     NUMERIC,
    tmean_c_z     NUMERIC,
    heat_days_z   NUMERIC,
    frost_days_z  NUMERIC,
    dry_spell_d_z NUMERIC,
    loaded_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (country_name, region, phase, crop_year)
);

-- Append-only: one block of rows per issue_date (the day the outlook was pulled),
-- so forecast skill can be backtested later. Never truncated by the loader.
-- Column names follow the Open-Meteo request; verify against a live response.
CREATE TABLE IF NOT EXISTS seasonal_outlook (
    country_name            TEXT NOT NULL,
    region                  TEXT NOT NULL,
    issue_date              DATE NOT NULL,
    time                    DATE NOT NULL,   -- the month being forecast
    temperature_2m_mean     NUMERIC,
    temperature_2m_anomaly  NUMERIC,
    precipitation_mean      NUMERIC,
    precipitation_anomaly   NUMERIC,
    loaded_at               TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (country_name, region, issue_date, time)
);

-- Example dashboard queries -------------------------------------------
-- Latest year snapshot:
-- SELECT * FROM coffee_country_year
-- WHERE year = (SELECT MAX(year) FROM coffee_country_year)
-- ORDER BY production DESC;

-- Exclude the USDA forecast year from 'actuals':
-- SELECT * FROM coffee_country_year WHERE NOT usda_is_forecast;

-- Data-quality check (should all be near zero):
-- SELECT country, year, balance_check FROM coffee_country_year
-- WHERE ABS(balance_check) > 100 ORDER BY ABS(balance_check) DESC;
