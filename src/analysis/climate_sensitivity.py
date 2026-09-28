"""
Does window-based weather explain yield at all? Test this BEFORE building
dashboards on top of the weather features.

Method (deliberately simple, predictors chosen in advance to avoid fishing):
  1. log(yield) per country, minus that country's linear time trend
     -> "detrended log yield": how far above/below trend a year was.
  2. Regress it on within-region z-scored weather in the flowering and fill
     windows, with country fixed effects and heteroskedasticity-robust SEs.
  3. Per-country single-window regressions (n ~ 30: read as hints, not proof).
  4. Sanity check: does the pooled model at least point the right way for
     Brazil's 2021 drought/frost crop?

Expect modest R^2. Coffee is also driven by biennial bearing, disease, prices
and management; a small but stable weather effect is a good outcome.
Requires: pip install statsmodels
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from config.settings import PROCESSED_DIR

PREDICTORS = [
    "flowering_rain_mm_z", "flowering_tmean_c_z",
    "fill_rain_mm_z", "fill_tmean_c_z", "fill_heat_days_z",
]
MIN_OBS = 5


def load() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED_DIR / "coffee_country_year.csv")
    if "yield_kg_ha" not in df.columns:
        raise SystemExit("yield_kg_ha missing - FAOSTAT data not merged.")
    df = df[df["yield_kg_ha"] > 0].dropna(subset=["yield_kg_ha"]).copy()
    if "fao_yield_is_official" in df.columns:
        # FAO yields for some countries are largely estimated/imputed (smooth,
        # weather-blind series). Check how much of the signal is real data.
        share = df.groupby("country")["fao_yield_is_official"].apply(lambda s: (s == True).mean())
        print("Share of FAO yield values flagged official/international, by country:")
        print(share.round(2).to_string())
        print("(If low for a country, its weather coefficients mostly test the imputation. "
              "Consider df = df[df.fao_yield_is_official == True] or using USDA production.)\n")
    df["log_yield"] = np.log(df["yield_kg_ha"])

    parts = []
    for country, g in df.groupby("country"):
        g = g.sort_values("year").copy()
        if len(g) >= 10:
            coef = np.polyfit(g["year"], g["log_yield"], 1)
            g["dlog_yield"] = g["log_yield"] - np.polyval(coef, g["year"])
        else:
            g["dlog_yield"] = np.nan
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def main():
    df = load()
    preds = [p for p in PREDICTORS if p in df.columns and df[p].notna().sum() > 30]
    if not preds:
        raise SystemExit("No usable weather z-score columns - run the extract + transform first.")

    d = df.dropna(subset=["dlog_yield"] + preds)
    print(f"\nPooled model on {len(d)} country-years, {d['country'].nunique()} countries")
    model = smf.ols("dlog_yield ~ " + " + ".join(preds) + " + C(country)", data=d).fit(cov_type="HC1")
    table = pd.DataFrame({"coef": model.params, "se": model.bse, "p": model.pvalues})
    table = table[~table.index.str.startswith("C(country)") & (table.index != "Intercept")]
    print(table.round(4).to_string())
    print(f"R^2 = {model.rsquared:.3f}  (includes country effects; the weather-only "
          f"contribution is smaller)")
    table.to_csv(PROCESSED_DIR / "climate_sensitivity_pooled.csv")

    print("\nPer-country sensitivity (dlog_yield ~ fill_rain_z + fill_tmean_z):")
    rows = []
    for country, g in df.groupby("country"):
        g = g.dropna(subset=["dlog_yield", "fill_rain_mm_z", "fill_tmean_c_z"]) \
            if {"fill_rain_mm_z", "fill_tmean_c_z"} <= set(df.columns) else g.iloc[0:0]
        if len(g) < MIN_OBS * 3:
            continue
        m = smf.ols("dlog_yield ~ fill_rain_mm_z + fill_tmean_c_z", data=g).fit(cov_type="HC1")
        rows.append({"country": country, "n": len(g),
                     "rain_coef": m.params["fill_rain_mm_z"], "rain_p": m.pvalues["fill_rain_mm_z"],
                     "temp_coef": m.params["fill_tmean_c_z"], "temp_p": m.pvalues["fill_tmean_c_z"]})
    if rows:
        per = pd.DataFrame(rows)
        print(per.round(3).to_string(index=False))
        per.to_csv(PROCESSED_DIR / "climate_sensitivity_by_country.csv", index=False)

    b = d[d["country"].str.contains("Brazil", case=False) & (d["year"] == 2021)]
    if not b.empty:
        pred = model.predict(b).iloc[0]
        print(f"\nBrazil 2021 check: actual detrended log-yield {b['dlog_yield'].iloc[0]:+.3f}, "
              f"model {pred:+.3f}. Same sign and roughly right size = encouraging; "
              f"model near zero = features miss the frost/drought mechanism.")


if __name__ == "__main__":
    main()
