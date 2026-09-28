-- Dashboard-facing materialized views.
-- Created by src/load/to_postgres.py after the tables are loaded (views are dropped
-- first via sql/drop_views.sql, because coffee_country_year is rebuilt on every load).
-- Point Looker Studio / Metabase / Superset at the mv_* views, not the raw tables.
-- Keep comments free of semicolons: the loader splits this file on them.
--
-- Units: USDA quantities are 1000 x 60 kg bags, exposed here as MILLION bags (_m_bags).
-- "Actual" = up to the current USDA estimate year. "Forecast" = USDA projection.

-- ---------------------------------------------------------------------------
-- 1. mv_country_year: one row per country x year, slim and dashboard-ready.
--    Use for trend lines (production, exports, stocks, prices) for any country.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_country_year AS
SELECT
    country,
    year,
    CASE WHEN usda_is_forecast THEN 'Forecast' ELSE 'Actual' END       AS status,
    ROUND((production / 1000.0)::numeric, 2)                           AS production_m_bags,
    ROUND((exports / 1000.0)::numeric, 2)                              AS exports_m_bags,
    ROUND((domestic_consumption / 1000.0)::numeric, 2)                 AS domestic_consumption_m_bags,
    ROUND((ending_stocks / 1000.0)::numeric, 2)                        AS ending_stocks_m_bags,
    stock_to_use_ratio,
    arabica_share_pct,
    export_intensity_pct,
    value_added_export_share_pct,
    production_yoy_pct,
    exports_yoy_pct,
    production_vs_prior5y_pct,
    production_share_of_scope_pct,      -- share among the countries loaded, NOT a world share
    ROUND(yield_kg_ha::numeric, 0)      AS yield_kg_ha,        -- FAO
    ROUND(area_harvested_ha::numeric, 0) AS area_harvested_ha,  -- FAO
    ROUND(producer_price_usd_per_tonne::numeric, 0)      AS producer_price_usd_per_tonne,       -- FAO farmgate, nominal
    ROUND(producer_price_real_usd_per_tonne::numeric, 0) AS producer_price_real_usd_per_tonne   -- FAO farmgate, constant dollars
FROM coffee_country_year;

CREATE INDEX idx_mv_country_year ON mv_country_year (country, year);

-- ---------------------------------------------------------------------------
-- 2. mv_country_snapshot: the headline table. Per country, the latest actual
--    year plus any forecast year, side by side.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_country_snapshot AS
WITH latest AS (
    SELECT country, MAX(year) AS year
    FROM mv_country_year
    WHERE status = 'Actual' AND production_m_bags IS NOT NULL
    GROUP BY country
)
SELECT c.*, 'Latest actual' AS snapshot
FROM mv_country_year c
JOIN latest l USING (country, year)
UNION ALL
SELECT c.*, 'Forecast' AS snapshot
FROM mv_country_year c
WHERE c.status = 'Forecast' AND c.production_m_bags IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. mv_weather_climatology: what is normal for each region x calendar month
--    (1991-2020 baseline, complete months only). Keep the baseline in sync with
--    BASELINE_START / BASELINE_END in config/agronomy.py.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_weather_climatology AS
SELECT
    country_name,
    region,
    month,
    ROUND(AVG(rain_mm), 3)            AS rain_mm_mean,
    ROUND(STDDEV_SAMP(rain_mm), 3)    AS rain_mm_sd,
    ROUND(AVG(temp_mean_c), 3)        AS temp_mean_c,
    ROUND(STDDEV_SAMP(temp_mean_c), 3) AS temp_sd_c,
    ROUND(AVG(heat_days), 2)          AS heat_days_mean,
    ROUND(AVG(max_dry_spell_d), 2)    AS dry_spell_d_mean,
    COUNT(*)                          AS n_years
FROM fact_weather_monthly
WHERE complete AND year BETWEEN 1991 AND 2020
GROUP BY country_name, region, month;

-- ---------------------------------------------------------------------------
-- 4. mv_weather_monthly_anomaly: every month vs its own normal.
--    Rain is shown as % of normal (rainfall is skewed, so z-scores mislead)
--    and temperature as a difference plus z-score.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_weather_monthly_anomaly AS
SELECT
    w.country_name,
    w.region,
    w.year,
    w.month,
    MAKE_DATE(w.year, w.month, 1)                                          AS month_start,
    w.rain_mm,
    ROUND((100 * w.rain_mm / NULLIF(c.rain_mm_mean, 0))::numeric, 0)       AS rain_pct_of_normal,
    w.temp_mean_c,
    ROUND((w.temp_mean_c - c.temp_mean_c)::numeric, 2)                     AS temp_anomaly_c,
    ROUND(((w.temp_mean_c - c.temp_mean_c) / NULLIF(c.temp_sd_c, 0))::numeric, 2) AS temp_z,
    w.heat_days,
    w.max_dry_spell_d,
    w.frost_days
FROM fact_weather_monthly w
JOIN mv_weather_climatology c USING (country_name, region, month)
WHERE w.complete;

CREATE INDEX idx_mv_weather_anom ON mv_weather_monthly_anomaly (country_name, region, month_start);

-- ---------------------------------------------------------------------------
-- 5. mv_phase_anomaly: flowering / fill / frost_season conditions per crop year
--    vs the region's own normal, with plain-language labels (+/- 1 SD).
--    is_latest marks the most recent fully observed window per region and phase.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_phase_anomaly AS
SELECT
    country_name,
    region,
    phase,
    crop_year,
    (crop_year = MAX(crop_year) OVER (PARTITION BY country_name, region, phase)) AS is_latest,
    ROUND(rain_mm::numeric, 0)      AS rain_mm,
    ROUND(rain_mm_z::numeric, 2)    AS rain_mm_z,
    ROUND(tmean_c::numeric, 2)      AS tmean_c,
    ROUND(tmean_c_z::numeric, 2)    AS tmean_c_z,
    heat_days,
    ROUND(heat_days_z::numeric, 2)  AS heat_days_z,
    dry_spell_d,
    ROUND(dry_spell_d_z::numeric, 2) AS dry_spell_d_z,
    frost_days,
    CASE WHEN rain_mm_z IS NULL THEN 'n/a'
         WHEN rain_mm_z <= -1 THEN 'Drier than normal'
         WHEN rain_mm_z >= 1  THEN 'Wetter than normal'
         ELSE 'Near normal' END AS rain_status,
    CASE WHEN tmean_c_z IS NULL THEN 'n/a'
         WHEN tmean_c_z <= -1 THEN 'Cooler than normal'
         WHEN tmean_c_z >= 1  THEN 'Warmer than normal'
         ELSE 'Near normal' END AS temp_status
FROM fact_weather_region_window;

-- ---------------------------------------------------------------------------
-- 6. mv_seasonal_outlook_latest: the most recent seasonal outlook only.
--    Directional risk signal, NOT a yield forecast. Anomalies are relative to the
--    forecast model's own climatology, and their units were not verified, so the
--    labels use the SIGN only.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_seasonal_outlook_latest AS
SELECT
    country_name,
    region,
    issue_date,
    time AS month_start,
    temperature_2m_mean,
    temperature_2m_anomaly,
    precipitation_mean,
    precipitation_anomaly,
    CASE WHEN precipitation_anomaly IS NULL THEN 'n/a'
         WHEN precipitation_anomaly > 0 THEN 'Wetter than normal'
         WHEN precipitation_anomaly < 0 THEN 'Drier than normal'
         ELSE 'Near normal' END AS rain_signal,
    CASE WHEN temperature_2m_anomaly IS NULL THEN 'n/a'
         WHEN temperature_2m_anomaly > 0 THEN 'Warmer than normal'
         WHEN temperature_2m_anomaly < 0 THEN 'Cooler than normal'
         ELSE 'Near normal' END AS temp_signal
FROM seasonal_outlook
WHERE issue_date = (SELECT MAX(issue_date) FROM seasonal_outlook);

-- ---------------------------------------------------------------------------
-- 7. mv_data_quality: how far to trust each country's numbers.
--    fao_yield_official_pct: share of FAO yield values flagged official (A) or
--    from an international organisation (X). Low = mostly estimated/imputed.
--    median_usda_fao_ratio: USDA production (tonnes) / FAO production, near 1 is good.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_data_quality AS
SELECT
    country,
    MIN(year) FILTER (WHERE production IS NOT NULL)                                AS first_usda_year,
    MAX(year) FILTER (WHERE production IS NOT NULL AND NOT usda_is_forecast)       AS last_actual_year,
    COUNT(*) FILTER (WHERE yield_kg_ha IS NOT NULL)                                AS fao_yield_years,
    ROUND((100.0 * COUNT(*) FILTER (WHERE fao_flag_yield IN ('A', 'X'))
           / NULLIF(COUNT(*) FILTER (WHERE yield_kg_ha IS NOT NULL), 0))::numeric, 0) AS fao_yield_official_pct,
    ROUND(AVG(ABS(balance_check))::numeric, 1)                                     AS avg_abs_balance_check,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY usda_production_mt / production_mt_fao)
           FILTER (WHERE production_mt_fao > 0 AND usda_production_mt IS NOT NULL))::numeric, 2) AS median_usda_fao_ratio
FROM coffee_country_year
GROUP BY country;
