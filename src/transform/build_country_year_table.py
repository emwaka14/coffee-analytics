"""
Build the analytical tables from the raw extracts.

Outputs (data/processed/):
  coffee_country_year.csv            one row per country x crop year
  weather_region_window_features.csv one row per region x window x crop year

TIME CONVENTION: `year` = crop year = USDA marketYear (the year harvest starts,
e.g. 2023 = the 2023/24 crop). FAOSTAT calendar-year figures are mapped to the
same integer. That's a good match for production/yield, but it's an assumption:
check_alignment() prints how well FAO and USDA production line up at lags
-1/0/+1 so you can see if a country needs shifting. Weather is NOT calendar
annual - it is aggregated inside phenology windows that belong to a crop year.

COUNTRY KEYS: everything is keyed on the names used in config.settings.COUNTRIES;
FAOSTAT 'Area' strings are mapped back to those keys (unmatched ones are printed).
"""
import re
from datetime import date

import numpy as np
import pandas as pd

from config.settings import RAW_DIR, PROCESSED_DIR, PSD_ATTRIBUTE_MAP, COUNTRIES
from src.transform.weather_features import region_window_features, country_features

FAO_TO_KEY = {info["faostat_name"]: key for key, info in COUNTRIES.items()}


# ------------------------------------------------------------------ helpers
def _map_fao_names(df: pd.DataFrame, col: str = "Area") -> pd.DataFrame:
    mapped = df[col].map(FAO_TO_KEY)
    missing = sorted(df.loc[mapped.isna(), col].unique())
    if missing:
        print(f"  WARNING: FAOSTAT areas with no match in COUNTRIES (dropped): {missing}")
    return df.assign(**{col: mapped}).dropna(subset=[col])


# ------------------------------------------------------------------- loaders
def _units_are_60kg_bags(df: pd.DataFrame) -> bool:
    """Everything downstream (tonne conversion, FAO cross-check, the *_m_bags views)
    assumes USDA coffee is reported in 1000 x 60 kg bags. Check it instead of trusting it."""
    if "unitDescription" not in df.columns:
        print("  WARNING: no unitDescription in the USDA file - cannot verify the unit is "
              "1000 x 60 kg bags; assuming it is.")
        return True
    units = df.loc[df["attributeName"] == "Production", "unitDescription"].dropna().unique()
    ok = len(units) > 0 and all(re.search(r"1000\D{0,3}60\D{0,3}KG", str(u), re.I) for u in units)
    if not ok:
        print(f"  WARNING: USDA production unit is {list(units)}, not '1000 x 60 KG BAGS'. "
              f"usda_production_mt is set to NaN, and the '_m_bags' dashboard labels and any "
              f"FAO cross-check are NOT valid until this is resolved.")
    return ok


def load_usda() -> pd.DataFrame:
    path = RAW_DIR / "usda_psd_latest.csv"
    if not path.exists():
        print(f"  Skipping USDA - {path.name} not found.")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df = df[df["attributeName"].isin(PSD_ATTRIBUTE_MAP.keys())].copy()
    df["attr_col"] = df["attributeName"].map(PSD_ATTRIBUTE_MAP)

    wide = df.pivot_table(index=["country_name", "marketYear"], columns="attr_col",
                          values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"country_name": "country", "marketYear": "year"})

    # USDA coffee units are 1000 x 60kg bags -> metric tonnes. Verify against
    # dim_unit before trusting; needed for the FAO cross-check.
    if "production" in wide.columns:
        wide["usda_production_mt"] = wide["production"] * 60 if _units_are_60kg_bags(df) else np.nan
    return wide


def load_faostat() -> pd.DataFrame:
    path = RAW_DIR / "faostat_coffee_latest.csv"
    if not path.exists():
        print(f"  Skipping FAOSTAT - {path.name} not found.")
        return pd.DataFrame()

    df = _map_fao_names(pd.read_csv(path))
    idx = ["Area", "Year"]
    wide = df.pivot_table(index=idx, columns="Element", values="Value", aggfunc="first")
    wide = wide.rename(columns={
        "Area harvested": "area_harvested_ha",
        "Yield": "yield_hg_ha",
        "Production": "production_mt_fao",   # kept separate from USDA on purpose
    })

    # Carry the FAO data-quality flag through instead of dropping it.
    # A = official, X = international org; E/I/M/... = estimated/imputed/missing.
    if "Flag" in df.columns:
        flags = df.pivot_table(index=idx, columns="Element", values="Flag", aggfunc="first")
        flags = flags.rename(columns={"Area harvested": "area", "Yield": "yield",
                                      "Production": "production"}).add_prefix("fao_flag_")
        wide = wide.join(flags)
        for k in ("production", "yield"):
            col = f"fao_flag_{k}"
            if col in wide.columns:
                wide[f"fao_{k}_is_official"] = wide[col].isin(["A", "X"])

    wide = wide.reset_index().rename(columns={"Area": "country", "Year": "year"})
    wide.columns.name = None
    if "yield_hg_ha" in wide.columns:
        wide["yield_kg_ha"] = wide["yield_hg_ha"] / 10   # 1 hg = 0.1 kg
    return wide


def load_weather() -> tuple[pd.DataFrame, pd.DataFrame]:
    path = RAW_DIR / "open_meteo_weather_monthly_latest.csv"
    if not path.exists():
        print(f"  Skipping weather - {path.name} not found (run src.extract.open_meteo).")
        return pd.DataFrame(), pd.DataFrame()
    region_df = region_window_features(pd.read_csv(path))
    if region_df.empty:
        return pd.DataFrame(), region_df
    return country_features(region_df), region_df


def load_prices() -> pd.DataFrame:
    path = RAW_DIR / "faostat_producer_prices_latest.csv"
    if not path.exists():
        return pd.DataFrame()
    df = _map_fao_names(pd.read_csv(path))
    out = (df.rename(columns={"Area": "country", "Year": "year"})
             [["country", "year", "producer_price_usd_per_tonne"]]
             .drop_duplicates(["country", "year"]))

    cpi_path = RAW_DIR / "us_cpi_latest.csv"
    if cpi_path.exists():
        cpi = pd.read_csv(cpi_path).set_index("year")["cpi"]
        cpi = cpi[cpi.index < date.today().year]   # this year's average is partial
        base_year = int(cpi.index.max())
        out["producer_price_real_usd_per_tonne"] = (
            out["producer_price_usd_per_tonne"] * cpi.loc[base_year] / out["year"].map(cpi)
        )
        print(f"  Prices deflated to {base_year} USD (US CPI).")
    else:
        print("  us_cpi_latest.csv not found - prices left NOMINAL. Run src.extract.us_cpi.")
    return out


# ------------------------------------------------------------------- checks
def check_alignment(df: pd.DataFrame) -> None:
    """Does FAO calendar-year production line up with USDA market-year production?"""
    if not {"usda_production_mt", "production_mt_fao"} <= set(df.columns):
        return
    print("FAO vs USDA production: correlation of YoY changes by lag (FAO shifted -1/0/+1 yrs):")
    for country, g in df.groupby("country"):
        g = g.set_index("year").sort_index()
        g = g.reindex(range(int(g.index.min()), int(g.index.max()) + 1))
        # Correlate YEAR-ON-YEAR changes, not levels: two trending series correlate
        # ~0.95+ at every lag, which would make the check meaningless.
        u = np.log(g["usda_production_mt"].where(lambda s: s > 0)).diff()
        f = np.log(g["production_mt_fao"].where(lambda s: s > 0)).diff()
        res = {lag: u.corr(f.shift(lag)) for lag in (-1, 0, 1)}
        best = max(res, key=lambda k: -1 if pd.isna(res[k]) else res[k])
        flag = "" if best == 0 else "   <-- best fit is NOT lag 0, review alignment"
        print(f"  {country:<22} " + "  ".join(f"{k:+d}:{v:.2f}" for k, v in res.items()) + flag)


# ------------------------------------------------------------------ metrics
def _yoy(df: pd.DataFrame, col: str) -> pd.Series:
    """YoY % change only where the previous row is really the previous year."""
    g = df.groupby("country")
    contiguous = (df["year"] - g["year"].shift(1)) == 1
    out = (df[col] / g[col].shift(1) - 1) * 100
    return out.replace([np.inf, -np.inf], np.nan).where(contiguous).round(1)


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["country", "year"]).reset_index(drop=True)
    # USDA marketYear Y = Oct Y - Sep Y+1. Until it ends, the *following* year is a
    # forecast, and the current one is still an estimate.
    today = date.today()
    current_my = today.year if today.month >= 10 else today.year - 1
    df["usda_is_forecast"] = df["year"] > current_my
    has = lambda *cols: all(c in df.columns for c in cols)

    # --- balance sheet ---
    if has("ending_stocks", "domestic_consumption", "exports"):
        denom = (df["domestic_consumption"] + df["exports"]).replace(0, np.nan)
        df["stock_to_use_ratio"] = (df["ending_stocks"] / denom).round(3)
    if has("ending_stocks", "beginning_stocks"):
        df["net_stock_change"] = df["ending_stocks"] - df["beginning_stocks"]
    if has("total_supply", "total_distribution"):
        df["balance_check"] = df["total_supply"] - df["total_distribution"]  # ~0 expected

    # --- composition ---
    if has("arabica_production", "robusta_production"):
        other = df["other_production"] if "other_production" in df.columns else 0
        total = (df["arabica_production"] + df["robusta_production"] + other).replace(0, np.nan)
        df["arabica_share_pct"] = (df["arabica_production"] / total * 100).round(1)

    if has("rg_exports", "soluble_exports", "exports"):
        value_added = df["rg_exports"].fillna(0) + df["soluble_exports"].fillna(0)
        share = value_added / df["exports"].replace(0, np.nan) * 100
        bad = share > 100
        if bad.any():
            # means 'exports' isn't the total on the same basis (bean-only, or
            # different green-bean-equivalent conversion) - don't publish nonsense
            print(f"  WARNING: value_added_export_share_pct >100% in {int(bad.sum())} rows; "
                  f"set to NaN. Check what PSD_ATTRIBUTE_MAP['exports'] points at.")
            share = share.mask(bad)
        df["value_added_export_share_pct"] = share.round(1)

    # --- dependency / intensity ---
    if has("exports", "production"):
        df["export_intensity_pct"] = (df["exports"] / df["production"].replace(0, np.nan) * 100).round(1)
    if has("imports", "total_supply"):
        df["import_dependency_pct"] = (df["imports"] / df["total_supply"].replace(0, np.nan) * 100).round(1)
    if has("production", "total_supply"):
        # renamed: this is production's share of total supply, not self-sufficiency
        df["production_share_of_supply_pct"] = (df["production"] / df["total_supply"].replace(0, np.nan) * 100).round(1)
    if "production" in df.columns:
        world = df.groupby("year")["production"].transform("sum")
        # share among the countries in COUNTRIES only - NOT a world share
        df["production_share_of_scope_pct"] = (df["production"] / world * 100).round(1)

    # --- change vs. recent history (replaces the START_YEAR-anchored cumsums,
    #     which depended on the window start and silently skipped gaps) ---
    for col in ["production", "exports", "domestic_consumption"]:
        if col in df.columns:
            df[f"{col}_yoy_pct"] = _yoy(df, col)
    for col in ["production", "exports"]:
        if col in df.columns:
            avg = df.groupby("country")[col].transform(
                lambda s: s.rolling(5, min_periods=3).mean().shift(1))  # prior 5 yrs
            df[f"{col}_prior5y_avg"] = avg
            df[f"{col}_vs_prior5y_pct"] = ((df[col] / avg.replace(0, np.nan) - 1) * 100).round(1)
    return df


# ---------------------------------------------------------------------- run
def run() -> pd.DataFrame:
    usda, fao, prices = load_usda(), load_faostat(), load_prices()
    weather, region_df = load_weather()

    if usda.empty and fao.empty:
        print("Nothing to merge - run the extract scripts first.")
        return pd.DataFrame()

    if usda.empty:
        merged = fao
    elif fao.empty:
        merged = usda
    else:
        merged = usda.merge(fao, on=["country", "year"], how="outer", validate="one_to_one")
        check_alignment(merged)

    for extra in [weather, prices]:
        if not extra.empty:
            merged = merged.merge(extra, on=["country", "year"], how="left", validate="one_to_one")

    merged = add_metrics(merged)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "coffee_country_year.csv"
    merged.to_csv(out_path, index=False)
    print(f"Wrote {len(merged):,} rows, {len(merged.columns)} columns -> {out_path}")
    if not region_df.empty:
        region_df.to_csv(PROCESSED_DIR / "weather_region_window_features.csv", index=False)
    return merged


if __name__ == "__main__":
    run()
