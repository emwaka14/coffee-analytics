-- Run before rebuilding the tables the views depend on (reverse dependency order).
DROP MATERIALIZED VIEW IF EXISTS mv_weather_monthly_anomaly CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_weather_climatology CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_phase_anomaly CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_seasonal_outlook_latest CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_country_snapshot CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_country_year CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_data_quality CASCADE;
