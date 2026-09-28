"""
Turn region x month weather into crop-year features.

Pipeline:
  1. For each region and crop year, aggregate monthly weather inside each
     phenology window (flowering, fill, ...) -> raw features.
  2. Standardise each feature against that region's own 1991-2020 baseline
     (z-score), so "wet" and "hot" mean *relative to that place's normal*.
  3. Only then aggregate to country, using production-share weights (or equal
     weights as a fallback), and keep the spread across regions.

Windows that are not fully covered by complete months are skipped (NaN), so a
half-finished season never masquerades as a full one.
"""
import numpy as np
import pandas as pd

from config.agronomy import (
    BASELINE_START, BASELINE_END, MIN_BASELINE_YEARS,
    NORTHERN_PATTERN, SOUTHERN_PATTERN, PHENOLOGY_OVERRIDES,
    SOUTHERN_LAT_CUTOFF, REGION_WEIGHTS,
)

# feature name -> (monthly column, how to combine months inside a window)
FEATURES = {
    "rain_mm":     ("rain_mm", "sum"),
    "tmean_c":     ("temp_mean_c", "mean"),
    "heat_days":   ("heat_days", "sum"),
    "frost_days":  ("frost_days", "sum"),
    "dry_spell_d": ("max_dry_spell_d", "max"),
}
KEYS = ["country_name", "region", "window"]


def windows_for(country: str, mean_lat: float) -> dict:
    if country in PHENOLOGY_OVERRIDES:
        return PHENOLOGY_OVERRIDES[country]
    return SOUTHERN_PATTERN if mean_lat < SOUTHERN_LAT_CUTOFF else NORTHERN_PATTERN


def _region_windows(g: pd.DataFrame, windows: dict) -> list[dict]:
    g = g[g["complete"]].copy()
    if g.empty:
        return []
    g["period"] = g["Year"] * 12 + g["month"] - 1          # months since year 0
    g = g.set_index("period").sort_index()
    y0, y1 = int(g["Year"].min()), int(g["Year"].max())
    out = []
    for win, (sy, sm, ey, em) in windows.items():
        for crop_year in range(y0, y1 + 1):
            start = (crop_year + sy) * 12 + sm - 1
            end = (crop_year + ey) * 12 + em - 1
            sel = g.loc[start:end]
            if len(sel) != end - start + 1:                 # window not fully observed
                continue
            row = {"window": win, "crop_year": crop_year}
            for feat, (col, how) in FEATURES.items():
                row[feat] = getattr(sel[col], how)()
            out.append(row)
    return out


def add_zscores(df: pd.DataFrame) -> pd.DataFrame:
    feats = list(FEATURES)
    base = df[df["crop_year"].between(BASELINE_START, BASELINE_END)]
    g = base.groupby(KEYS)[feats]
    stats = pd.concat([
        g.mean().add_suffix("__mu"),
        g.std().add_suffix("__sd"),
        g.count().add_suffix("__n"),
    ], axis=1).reset_index()
    out = df.merge(stats, on=KEYS, how="left")
    for f in feats:
        ok = (out[f + "__n"] >= MIN_BASELINE_YEARS) & (out[f + "__sd"] > 0)
        # z is undefined where the baseline never varies (e.g. frost days in the
        # tropics) - that's NaN on purpose; use the raw count there.
        out[f + "_z"] = np.where(ok, (out[f] - out[f + "__mu"]) / out[f + "__sd"], np.nan)
    return out.drop(columns=[c for c in out.columns if c.endswith(("__mu", "__sd", "__n"))])


def region_window_features(monthly: pd.DataFrame) -> pd.DataFrame:
    """One row per region x window x crop_year, with raw and z-scored features."""
    mean_lat = monthly.groupby("country_name")["lat"].mean()
    records = []
    for (country, region), g in monthly.groupby(["country_name", "region"]):
        for r in _region_windows(g, windows_for(country, mean_lat[country])):
            r.update(country_name=country, region=region)
            records.append(r)
    if not records:
        return pd.DataFrame()
    return add_zscores(pd.DataFrame(records))


def _wavg(values: pd.Series, w: np.ndarray) -> float:
    m = values.notna().to_numpy()
    if not m.any() or w[m].sum() <= 0:
        return np.nan
    return float(np.average(values.to_numpy()[m], weights=w[m]))


def country_features(region_df: pd.DataFrame) -> pd.DataFrame:
    """Weighted country aggregation. Columns: {window}_{feature}, _z, _z_spread."""
    recs: dict[tuple, dict] = {}
    for (country, win, year), g in region_df.groupby(["country_name", "window", "crop_year"]):
        wmap = REGION_WEIGHTS.get(country)
        w = (g["region"].map(wmap).fillna(0).to_numpy(float) if wmap
             else np.ones(len(g)))
        rec = recs.setdefault((country, year), {"country": country, "year": year})
        for f in FEATURES:
            rec[f"{win}_{f}"] = _wavg(g[f], w)
            rec[f"{win}_{f}_z"] = _wavg(g[f + "_z"], w)
            z = g[f + "_z"].dropna()
            # disagreement between regions: one region in drought, another fine
            rec[f"{win}_{f}_z_spread"] = (z.max() - z.min()) if len(z) > 1 else np.nan
        rec[f"{win}_n_regions"] = len(g)
    return pd.DataFrame(list(recs.values()))
