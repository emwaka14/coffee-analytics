# Changelog: codebase changes

Everything that differs from your original project, file by file. Paths are relative to the project root.

## Summary of files

| File | Status | What changed |
|---|---|---|
| `config/settings.py` | replaced | New dates, regions, DB SSL setting (details below) |
| `config/agronomy.py` | **new** | Phenology windows, baseline, thresholds, region weights |
| `sql/schema.sql` | replaced | Weather tables, seasonal table with `issue_date`; wide metrics table no longer hand-defined |
| `sql/views.sql` | **new** | 7 dashboard materialized views |
| `sql/drop_views.sql` | **new** | Drops the views before each reload |
| `src/extract/open_meteo.py` | rewritten | Region × month output, extremes, cache, rate-limit handling |
| `src/extract/open_meteo_seasonal.py` | patched | `issue_date`, response-key check |
| `src/extract/faostat_prices.py` | patched | Annual rows only, flexible element match, de-duplication |
| `src/extract/usda_psd.py` | patched | Keeps whole latest-revision rows |
| `src/extract/us_cpi.py` | **new** | US CPI (FRED, or World Bank fallback) |
| `src/extract/faostat.py` | unchanged | |
| `src/extract/_utils.py` | unchanged | |
| `src/transform/build_country_year_table.py` | rewritten | Name mapping, flags, real prices, weather windows, fixed metrics |
| `src/transform/weather_features.py` | **new** | Windows, z-scores, weighted country aggregation |
| `src/analysis/__init__.py` | **new** | Empty; makes the folder importable |
| `src/analysis/climate_sensitivity.py` | **new** | Weather vs yield test |
| `src/load/to_postgres.py` | rewritten | Schema-aware loader, seasonal history, views |
| `README.md` | replaced | Setup, run order, views, limits, checklists |
| `requirements.txt` | edit by hand | Add `statsmodels` |
| `.env` | edit by hand | Optional: `FRED_API_KEY`, `DB_SSLMODE` |

---

## Details by file

### `config/settings.py`
- `START_YEAR` 2000 → **1993** (more years for the climate test; FAOSTAT's Ethiopia name changes before 1993).
- `END_DATE`: was "yesterday"; now **today − 7 days**, capped at year end (Open-Meteo's archive lags several days).
- **Uganda East** moved from the Mount Elgon summit (~4,300 m) to the Bugisu coffee belt (approximate).
- Added regions: Brazil (Cerrado Mineiro, Mogiana, Matas de Minas, Espírito Santo), Viet Nam (Gia Lai, Dak Nong, Lam Dong). Coordinates approximate, verify.
- Optional `elevation` (m) on regions, for temperature downscaling.
- New `DB_SSLMODE` (default `require`).
- Comment typo fixed (`usda_country_code`).

### `config/agronomy.py` (new)
Weather history start (1991), baseline 1991–2020, heat/frost/dry-day thresholds (Viet Nam heat override 34 °C), phenology windows (`flowering`, `fill`, Brazil `frost_season`), and `REGION_WEIGHTS` (empty = equal weights). These are approximations, so validate them.

### `src/extract/open_meteo.py` (rewritten)
- Output is **region × month**: mean/max/min temperature, rain, wet days, longest dry spell, heat days, frost days, `complete` flag.
- **Per-region disk cache** (`data/raw/cache/open_meteo_monthly/`), keyed on coordinates/elevation/thresholds. Finished regions are never lost or refetched.
- **Incremental refresh:** cached regions fetch only from the last cached month onward.
- **Rate-limit handling:** free tier is 600/min, 5,000/hour, 10,000/day, weighted by size (~370 calls for one region's history). The script paces by estimated cost, stops at ~4,500 calls per run, detects hourly/daily 429s, and resumes on re-run. `--wait` sleeps through the hourly limit.
- The combined `_latest.csv` is written only when all regions are complete.
- Prints the API's message on non-429 errors (e.g. a rejected `elevation`).

### `src/extract/open_meteo_seasonal.py` (patched)
- Every pull stamped with `issue_date` so history accumulates and can be backtested.
- Raises a clear error if the response has no `monthly` key.

### `src/extract/faostat_prices.py` (patched)
- Annual rows only (drops monthly rows if a `Months` column exists).
- Element matched by "Producer Price" + "USD" instead of one exact label.
- Duplicates removed per country-year.

### `src/extract/usda_psd.py` (patched)
- Latest revision per (country, marketYear, attribute) now uses `drop_duplicates(keep="last")`. The old `groupby().last()` could splice fields from different revisions.

### `src/extract/us_cpi.py` (new)
US CPI annual average. Uses FRED if `FRED_API_KEY` is set, else the World Bank series. Used to deflate prices.

### `src/transform/build_country_year_table.py` (rewritten)
- FAO country names mapped to your `COUNTRIES` keys; unmatched names printed. Merges use `validate="one_to_one"`.
- FAO quality flags carried through (`fao_flag_*`, `fao_*_is_official`); `yield_kg_ha` added.
- `check_alignment()`: FAO vs USDA production, **YoY changes** at lags −1/0/+1 (not levels, which correlate at every lag when trending).
- Weather now comes from phenology-window features (below), not annual means.
- Prices deflated to constant dollars (`producer_price_real_usd_per_tonne`); base year excludes the current partial year.
- `usda_is_forecast` flag.
- Metrics: YoY only across consecutive years; cumulative sums replaced by `*_vs_prior5y_pct`; `value_added_export_share_pct` set to NaN with a warning when >100%; zero denominators guarded.
- **Removed columns:** `avg_temp_c`, `total_rain_mm`, `*_cumulative`. **Renamed:** `self_sufficiency_pct` → `production_share_of_supply_pct`. **New:** `production_share_of_scope_pct` (share among loaded countries, not a world share).

### `src/transform/weather_features.py` (new)
Region × window × crop-year features (rain, mean temp, heat days, frost days, dry spell), z-scored against each region's own 1991–2020 baseline, then aggregated to country with weights, plus the spread across regions. Incomplete windows are NaN.

### `src/analysis/climate_sensitivity.py` (new)
Detrended log yield regressed on pre-chosen flowering/fill z-scores with country effects and robust SEs; per-country estimates; Brazil 2021 sanity check; prints the share of official FAO yield values per country first.

### `sql/schema.sql`
- Added `fact_weather_monthly` and `fact_weather_region_window` (column `phase`, since `window` is a reserved word).
- `seasonal_outlook` gained `issue_date` (primary key includes it).
- `coffee_country_year` is no longer defined here (~90 evolving columns); the loader rebuilds it and adds `PRIMARY KEY (country, year)`.

### `sql/views.sql` and `sql/drop_views.sql` (new)
Seven materialized views: `mv_country_snapshot`, `mv_country_year`, `mv_phase_anomaly`, `mv_weather_monthly_anomaly`, `mv_weather_climatology`, `mv_seasonal_outlook_latest`, `mv_data_quality`. Dropped before each reload so they never block a rebuild.

### `src/load/to_postgres.py` (rewritten)
- Applies `schema.sql` automatically on every run.
- Connection built with `URL.create` (passwords with special characters work); SSL mode configurable.
- `_append()` loads only columns the target table has and says which it skipped.
- `dim_attribute.short_name` now populated from `PSD_ATTRIBUTE_MAP`; warns about map names USDA doesn't return.
- Weather tables truncated and reloaded; `coffee_country_year` rebuilt with a primary key.
- `seasonal_outlook` is **append-only** by `issue_date`, backfilled from every dated raw file; a legacy table without `issue_date` is dropped once.
- Drops the views first, recreates them at the end; a failing view statement is named without stopping the rest.
- `--refresh` refreshes the views only.

---

## Tested and untested

**Tested** (synthetic data generated from your real `settings.py`, and a real embedded Postgres 16): weather features, the build, the alignment check, the analysis script, cache/stop/resume/incremental refresh against a simulated rate-limited API, and the full loader plus all views, including a second load with views present and a `--refresh`.

**Not tested:** any live API call (Open-Meteo archive and seasonal, FRED/World Bank, FAOSTAT prices, USDA) and your real data. Unverified assumptions: the seasonal endpoint's response keys, the `elevation` parameter, the FAO Prices element label, and USDA's unit being 1000 × 60 kg bags. Each fails with a message or a warning rather than silently.
