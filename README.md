# Coffee Analytics

A data pipeline and analytics database for understanding **coffee supply and climate risk** in four producing countries, with a deeper regional focus on **Uganda**.

It pulls public supply, production, price and weather data, turns raw weather into coffee-relevant climate signals, and loads everything into Postgres, with ready-made views for dashboards.

**Countries in scope:** Uganda, Ethiopia, Brazil, Viet Nam (configurable in `config/settings.py`).

---

## Purpose

Coffee markets move on supply, and supply moves on weather. This project brings the two together in one reproducible place so you can answer, from your own database:

- **How is supply developing?** Production, exports, stocks and stock-to-use for each country, and how the current or forecast crop compares with the recent average.
- **What is the crop mix?** Arabica vs Robusta share, and how much is exported as green beans vs value-added products.
- **How do prices relate to supply?** Real (inflation-adjusted) farmgate prices against production and stocks.
- **What are growing conditions like right now?** Were flowering and fruit-fill in each region wetter, drier, hotter or cooler than that region's normal?
- **What does the seasonal outlook say?** A wetter/drier, warmer/cooler signal for the months ahead, archived by issue date so it can be checked against what actually happened.
- **Uganda in detail:** the same questions at region level (South West, East, Central), where weather data allows.

### What it is not
- **Not a yield forecast.** The seasonal outlook is a directional risk signal, and the climate-sensitivity script tests whether weather explains yield. It does not predict it.
- **Not a world supply view.** Only the countries you load are covered, so "share" metrics are shares of those countries, not of the world.
- **Not regional yield analysis.** Public regional yield series are not available here, so regional work is about weather conditions, not regional output.

---

## Data sources

| Source | What it provides | Granularity | Key needed |
|---|---|---|---|
| **USDA FAS PSD** | Production, Arabica/Robusta split, imports, exports, consumption, stocks | Country × market year | `USDA_API_KEY` (free) |
| **FAOSTAT** (bulk download) | Area harvested, yield, production, with data-quality flags | Country × year | none |
| **FAOSTAT Prices** (bulk download) | Producer (farmgate) prices, USD/tonne | Country × year | none |
| **Open-Meteo Archive** (ERA5) | Daily temperature and rainfall, aggregated to monthly with extremes | Region × month, from 1991 | none |
| **Open-Meteo Seasonal** (ECMWF SEAS5) | Monthly outlook for the next ~7 months | Region × month, per issue date | none |
| **FRED** or **World Bank** | US CPI, to deflate prices to constant dollars | Year | `FRED_API_KEY` optional |

Open-Meteo's free tier is for **non-commercial use** and its data is licensed CC BY 4.0, so keep the attribution if you publish anything. Check its terms if the project becomes commercial.

---

## How it works

```
 EXTRACT (src/extract)                TRANSFORM (src/transform)            LOAD (src/load)
 ─────────────────────                ─────────────────────────            ───────────────
 usda_psd            ─┐
 faostat             ─┤               build_country_year_table.py
 faostat_prices      ─┼─ data/raw ─►   ├─ name mapping, units, flags   ─►   to_postgres.py
 us_cpi              ─┤   *_latest     ├─ weather_features.py                 ├─ dims, facts, weather
 open_meteo (cached) ─┤   .csv         └─ derived metrics                     ├─ coffee_country_year
 open_meteo_seasonal ─┘                                                       ├─ seasonal_outlook (history)
                                       data/processed                         └─ mv_* dashboard views
                                       ├─ coffee_country_year.csv
                                       └─ weather_region_window_features.csv

 ANALYSE (src/analysis): climate_sensitivity.py, does weather explain yield?
```

Every extract saves a timestamped raw file plus a `*_latest.csv` pointer, so nothing is silently overwritten and transforms always have a stable filename.

---

## Key concepts

**Crop year.** Everything is aligned to the USDA marketYear, i.e. the year harvest starts (2024 = the 2024/25 crop). FAO calendar years are mapped to the same integer, and `check_alignment()` reports whether that fits each country.

**Phenology windows, not calendar years.** Coffee responds to weather at specific stages. Weather is aggregated inside stage windows (`flowering`, `fill`, and a Brazil-only `frost_season`) that belong to a crop year. The windows live in `config/agronomy.py`.

**Anomalies, not absolutes.** Each window feature is standardised (z-score) against that region's own 1991–2020 baseline, so "wetter than normal" means normal *for that place*. Regions are combined into a country only afterwards, using production-share weights (equal weights if none are set), and the spread between regions is kept.

**Extremes matter.** Alongside means, the pipeline counts heat days, frost days and the longest dry spell per month.

**Actual vs forecast.** USDA's current projection year is flagged (`usda_is_forecast`, or `status = 'Forecast'` in the views).

**Units.** USDA quantities are 1000 × 60 kg bags (views show million bags, `_m_bags`). FAO production is in tonnes and yield in hg/ha (also given in kg/ha). Prices are USD per tonne, nominal and real.

---

## Project layout

```
config/
  settings.py          countries, regions, keys, dates, database settings
  agronomy.py          phenology windows, baseline, thresholds, region weights
sql/
  schema.sql           dimension, fact, weather and seasonal tables
  views.sql            dashboard materialized views (mv_*)
  drop_views.sql       drops the views before each reload
src/
  extract/             one script per source (+ _utils.py shared helpers)
  transform/           build_country_year_table.py, weather_features.py
  analysis/            climate_sensitivity.py
  load/                to_postgres.py
data/
  raw/                 timestamped extracts, *_latest.csv, cache/
  processed/           analytical tables
notebooks/             exploration
CHANGELOG.md           history of changes to the codebase
```

---

## Getting started

### 1. Install
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                        # includes statsmodels
```

### 2. Configure `.env`
| Variable | Required | Notes |
|---|---|---|
| `USDA_API_KEY` | yes | https://api.data.gov/signup/ |
| `USDA_BASE_URL` | no | default `https://api.fas.usda.gov/api` |
| `FRED_API_KEY` | no | more current CPI; falls back to World Bank without it |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | for loading | e.g. from your Aiven service |
| `DB_SSLMODE` | no | default `require`; use `prefer` or `disable` for a local Postgres |

### 3. Run
From the project root, always with `python -m`:

```bash
# Extract
python -m src.extract.open_meteo            # slow on first run, see "Open-Meteo limits"
python -m src.extract.us_cpi
python -m src.extract.usda_psd
python -m src.extract.faostat
python -m src.extract.faostat_prices
python -m src.extract.open_meteo_seasonal   # re-run monthly to build forecast history

# Transform
python -m src.transform.build_country_year_table

# Analyse (optional, but run it before trusting the weather features)
python -m src.analysis.climate_sensitivity

# Load (applies schema.sql, loads tables, creates the views)
python -m src.load.to_postgres
```

After a new seasonal pull you can refresh just the views: `python -m src.load.to_postgres --refresh`.

### Open-Meteo limits
The free tier allows 600 calls/minute, 5,000/hour and 10,000/day, and requests are weighted by size. One region's 35-year history costs roughly 370 calls, so the full first pull (~15 regions) takes more than an hour of quota.

- Each finished region is cached in `data/raw/cache/open_meteo_monthly/`, so nothing is lost when the script stops.
- The script stops before the hourly limit. Re-run it after an hour, or use `--wait` to let it sleep through the limit.
- Later runs are incremental (about one call per region).
- The combined `open_meteo_weather_monthly_latest.csv` is written only when **every** region is complete.
- Changing a region's coordinates, elevation or thresholds refetches only that region. Delete the cache folder to force a full refetch.

---

## Outputs

### Database tables
| Table | Contents |
|---|---|
| `dim_country`, `dim_attribute`, `dim_unit` | USDA reference data |
| `fact_psd_annual` | USDA PSD in long format (latest revision per key), source of truth |
| `fact_weather_monthly` | Region × month weather and extremes |
| `fact_weather_region_window` | Region × phase × crop year features, raw and z-scored |
| `seasonal_outlook` | Append-only outlook history keyed by `issue_date` |
| `coffee_country_year` | Wide country × year table: USDA + FAO + prices + weather windows + derived metrics |

### Dashboard views
Point your BI tool (Looker Studio, Metabase, Superset...) at the `mv_*` views. They are dropped and recreated on every full load, so they never block a rebuild.

| View | One row per | Use |
|---|---|---|
| `mv_country_snapshot` | country × (latest actual, forecast) | Headline table: production, exports, stocks, stock-to-use, YoY, vs 5-year average |
| `mv_country_year` | country × year | Trend lines for any country |
| `mv_phase_anomaly` | region × phase × crop year | Was flowering/fill wetter, drier, hotter, cooler than normal? Filter `is_latest` for the current season |
| `mv_weather_monthly_anomaly` | region × month | Rain as % of normal, temperature anomaly, heat days, dry spells |
| `mv_weather_climatology` | region × calendar month | The "normal" reference (1991–2020) |
| `mv_seasonal_outlook_latest` | region × forecast month | Latest outlook as a directional signal (sign only) |
| `mv_data_quality` | country | Official-data share, balance check, USDA vs FAO agreement |

Suggested dashboard pages: (1) four-country snapshot, (2) Uganda: trends, this season's status by region, outlook, (3) data quality.

---

## Configuration you should review

Some values are judgment calls or approximations. Check them before drawing conclusions.

- **`COUNTRIES`**: confirm the USDA country codes against USDA's reference list.
- **`PSD_ATTRIBUTE_MAP`**: the loader warns about names USDA doesn't return.
- **`REGIONS`**: coordinates are approximate town or district centroids. Elevations are rough.
- **`REGION_WEIGHTS`** (`config/agronomy.py`): empty means equal weights. Fill from national production statistics.
- **Phenology windows and thresholds** (`config/agronomy.py`): general-agronomy approximations, not local calendars. Validate with an agronomist or national coffee board. Bimodal producers such as Uganda are not modelled with two cycles yet.
- **`START_YEAR` / `END_YEAR`**: `END_YEAR` includes the USDA forecast year. Set it to last year for actuals only.

---

## Data quality and limitations

- **FAO yields can be largely estimated**, particularly for some African producers. The analysis prints the share flagged official; `mv_data_quality` shows it too.
- **Weather is modelled reanalysis at a point**, not station data, and regions are single points. Elevation downscaling helps but is approximate.
- **Expect modest climate signals.** Coffee yield also depends on biennial bearing, disease, prices and management. Country-level annual data has few observations, and published studies find weak or no weather signal in some countries (Brazil in particular).
- **Farmgate prices lag the market** and end a year or two behind. They are not a market benchmark.
- **Unverified assumptions**, each of which fails with a message or a warning rather than silently: the seasonal endpoint's response keys, Open-Meteo's `elevation` parameter, the FAO Prices element label, the CPI response formats, and USDA's unit being 1000 × 60 kg bags.

---

## Extending it

- **Add a country:** add it to `COUNTRIES` (with its FAOSTAT name and USDA code). USDA and FAO data need nothing more. Add `REGIONS` entries only if you want weather for it.
- **Add a region:** add it to `REGIONS` (optionally with `elevation`) and re-run `open_meteo`. Only the new region is fetched.
- **Add a data source:** write an extract script that calls `save_raw`, then merge it in `build_country_year_table.py`.
- **Add a view:** put the `CREATE MATERIALIZED VIEW` in `sql/views.sql`, its `DROP` in `sql/drop_views.sql`, and its name in `MV_ORDER` in `to_postgres.py`. Keep semicolons out of SQL comments, because the loader splits on them.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: src...` | Run from the project root with `python -m`; every folder under `src/` needs an `__init__.py` |
| `Stopping: local hourly budget...` from `open_meteo` | Expected on the first pull. Re-run in about an hour, or use `--wait` |
| `Unexpected seasonal response keys` | Print the response and update the parser in `open_meteo_seasonal.py` |
| FAO prices: "No rows matched" | Print `df["Element"].unique()` and adjust the filter in `faostat_prices.py` |
| Warning about FAOSTAT areas with no match | Correct `faostat_name` in `COUNTRIES` |
| `value_added_export_share_pct >100%` warning | Check what `PSD_ATTRIBUTE_MAP["exports"]` points at |
| `create views ... FAILED` on load | A column the view needs is missing (often an attribute name mismatch); the message names the statement |
| SSL error connecting locally | Set `DB_SSLMODE=prefer` or `disable` |
| Alignment check flags a country | Its best FAO/USDA fit isn't lag 0; consider shifting that country's FAO years |

---

## Licence and attribution

Add your own licence for the code. Data licences: Open-Meteo data is CC BY 4.0 (free tier is non-commercial); USDA and FAOSTAT data are subject to their publishers' terms of use.