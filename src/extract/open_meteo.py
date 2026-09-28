"""
Extract daily weather for each growing region and derive REGION x MONTH tables.

TWO LAYERS (this is what removes the API-limit bottleneck):
  1. RAW DAILY CACHE   data/raw/cache/open_meteo_daily/<region>.csv
     The API's own daily numbers (Tmean/Tmax/Tmin/precip). Keyed only on what changes
     the REQUEST (lat, lon, elevation, start date). Pulled once, then topped up.
  2. DERIVED MONTHLY   data/raw/open_meteo_weather_monthly_latest.csv
     Rebuilt from the daily cache on EVERY run, with no API calls. So changing heat,
     frost or dry-day thresholds in config/agronomy.py (or adding a new feature such
     as diurnal range) costs zero calls. The old design cached monthly values with the
     thresholds in the cache key, so every threshold tweak meant a full re-pull.

Why monthly at all: coffee responds to *when* weather happens and to extremes, so we
keep monthly means plus extreme counts (heat days, frost days, longest dry spell).

RATE LIMITS (free tier): 600 calls/min, 5,000/hour, 10,000/day. A request is weighted
roughly (variables / 10) x (days / 14), minimum 1, so 35 years x 4 variables for one
region is ~370 calls and the first full pull for ~15 regions (~5,500) does not fit in
one hour. This script therefore: paces by estimated cost, stops cleanly before the
hourly budget (finished regions are already on disk), and resumes on re-run.
After the first pull a refresh is ~2 calls per region.

REFRESH WINDOW: each run re-fetches the last OVERLAP_DAYS days, not just new ones. ERA5's
most recent weeks are preliminary (ERA5T) and are occasionally revised, and the last few
days may come back empty. Overwriting them fixes both, for ~2 calls per region.

Usage:
  python -m src.extract.open_meteo            fetch what fits in this hour, then stop
  python -m src.extract.open_meteo --wait     sleep through the hourly limit and continue
  python -m src.extract.open_meteo --status   show cache coverage per region (no API calls)

Optional: give a region an "elevation" (metres) in REGIONS to have Open-Meteo downscale
temperature to the farms' altitude. No API key needed. Free for non-commercial use.
"""
import calendar
import hashlib
import math
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

from config.settings import REGIONS, END_DATE, RAW_DIR
from config.agronomy import (
    WEATHER_START_DATE, HEAT_THRESHOLD_C, HEAT_THRESHOLD_OVERRIDES,
    FROST_THRESHOLD_C, WET_DAY_MM,
)

API_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = "temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum"
N_VARS = DAILY_VARS.count(",") + 1

# Stay comfortably inside the free limits (600/min, 5,000/hour).
MINUTE_BUDGET = 450
HOURLY_BUDGET = 4500
MAX_RETRIES = 5
MINUTE_WAIT_SEC = 65
OVERLAP_DAYS = 60

DAILY_CACHE_DIR = RAW_DIR / "cache" / "open_meteo_daily"
OUT_PATH = RAW_DIR / "open_meteo_weather_monthly_latest.csv"


class RateLimitStop(Exception):
    """Hourly/daily limit (real or budgeted) reached - stop and resume later."""


# ------------------------------------------------------------------ helpers
def estimate_cost(start: str, end: str) -> int:
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    return max(1, math.ceil(N_VARS / 10 * days / 14))


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def _request(params: dict) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(API_URL, params=params, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            try:
                reason = resp.json().get("reason", "")
            except ValueError:
                reason = resp.text[:200]
            low = reason.lower()
            if "hourly" in low or "daily" in low or "monthly" in low:
                raise RateLimitStop(reason or "hourly/daily limit reached")
            print(f"  Minute limit hit ({reason or '429'}); waiting {MINUTE_WAIT_SEC}s "
                  f"(attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(MINUTE_WAIT_SEC)
            continue
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}")   # e.g. a rejected parameter
        resp.raise_for_status()
    raise RuntimeError(f"Gave up after {MAX_RETRIES} rate-limit retries.")


def fetch_daily(lat, lon, start, end, elevation=None) -> pd.DataFrame:
    params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "daily": DAILY_VARS, "timezone": "auto"}
    if elevation is not None:
        params["elevation"] = elevation
    daily = pd.DataFrame(_request(params)["daily"])
    daily["time"] = pd.to_datetime(daily["time"])
    return daily


def to_monthly(daily: pd.DataFrame, heat_c: float = HEAT_THRESHOLD_C) -> pd.DataFrame:
    """Daily -> monthly means, totals and extreme-event counts."""
    d = daily.copy()
    d["Year"] = d["time"].dt.year
    d["month"] = d["time"].dt.month
    rows = []
    for (year, month), g in d.groupby(["Year", "month"]):
        precip = g["precipitation_sum"]
        n_days = int(precip.notna().sum())
        rows.append({
            "Year": year,
            "month": month,
            "temp_mean_c": g["temperature_2m_mean"].mean(),
            "tmax_mean_c": g["temperature_2m_max"].mean(),
            "tmin_mean_c": g["temperature_2m_min"].mean(),
            "tmin_abs_c": g["temperature_2m_min"].min(),
            "rain_mm": precip.sum(min_count=1),
            "wet_days": int((precip >= WET_DAY_MM).sum()),
            # longest dry run *within* the month (not across month borders)
            "max_dry_spell_d": _longest_run((precip < WET_DAY_MM).to_numpy()),
            "heat_days": int((g["temperature_2m_max"] >= heat_c).sum()),
            "frost_days": int((g["temperature_2m_min"] <= FROST_THRESHOLD_C).sum()),
            "n_days": n_days,
            # partial months (the most recent one) are flagged and dropped downstream
            "complete": n_days == calendar.monthrange(year, month)[1],
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- cache
def _daily_cache_path(country, region, lat, lon, elevation):
    # Only request-defining inputs belong in the key. Thresholds do NOT.
    key = f"{lat}|{lon}|{elevation}|{WEATHER_START_DATE}|{DAILY_VARS}"
    digest = hashlib.md5(key.encode()).hexdigest()[:8]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{country}_{region}").strip("_")
    return DAILY_CACHE_DIR / f"{slug}_{digest}.csv"


def get_region_daily(country, region, coords, spent):
    """Return (daily_df, estimated_cost_spent). Fetches only what the cache lacks."""
    lat, lon, elev = coords["lat"], coords["lon"], coords.get("elevation")
    path = _daily_cache_path(country, region, lat, lon, elev)
    cached = pd.read_csv(path, parse_dates=["time"]) if path.exists() else None

    if cached is not None and len(cached):
        last = cached["time"].max()
        if last >= pd.Timestamp(END_DATE):
            print("  cached, up to date")
            return cached, 0
        start = max(pd.Timestamp(WEATHER_START_DATE),
                    last - pd.Timedelta(days=OVERLAP_DAYS)).strftime("%Y-%m-%d")
        print(f"  cached through {last.date()}; refreshing from {start}")
    else:
        start = WEATHER_START_DATE

    cost = estimate_cost(start, END_DATE)
    if spent + cost > HOURLY_BUDGET:
        raise RateLimitStop(f"local hourly budget ({spent} used + {cost} needed > {HOURLY_BUDGET})")

    new = fetch_daily(lat, lon, start, END_DATE, elev)
    df = new if cached is None else pd.concat([cached, new], ignore_index=True)
    df = (df.drop_duplicates("time", keep="last")            # newly fetched rows win
            .sort_values("time").reset_index(drop=True))
    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

    time.sleep(max(1.0, cost / MINUTE_BUDGET * 60))          # pace by cost, not a flat 2s
    return df, cost


def region_monthly(daily: pd.DataFrame, country, region, coords) -> pd.DataFrame:
    """Derive the monthly table from cached daily data (no API call)."""
    heat_c = HEAT_THRESHOLD_OVERRIDES.get(country, HEAT_THRESHOLD_C)
    m = to_monthly(daily, heat_c)
    m["country_name"], m["region"] = country, region
    m["lat"], m["lon"] = coords["lat"], coords["lon"]
    m["elevation_m"] = coords.get("elevation")
    m["heat_threshold_c"] = heat_c          # so heat_days stays interpretable
    return m


# ------------------------------------------------------------------- status
def _all_regions():
    return [(c, r, co) for c, regs in REGIONS.items() for r, co in regs.items()]


def status():
    print(f"Daily cache: {DAILY_CACHE_DIR}\nTarget: {WEATHER_START_DATE} -> {END_DATE}")
    done = 0
    for country, region, co in _all_regions():
        p = _daily_cache_path(country, region, co["lat"], co["lon"], co.get("elevation"))
        if not p.exists():
            print(f"  {country} - {region}: not cached")
            continue
        t = pd.read_csv(p, usecols=["time"], parse_dates=["time"])["time"]
        full = t.min() <= pd.Timestamp(WEATHER_START_DATE) + pd.Timedelta(days=31)
        done += full
        print(f"  {country} - {region}: {t.min().date()} -> {t.max().date()} ({len(t):,} days)"
              f"{'' if full else '  INCOMPLETE'}")
    print(f"{done}/{len(_all_regions())} regions have full history.")


# ---------------------------------------------------------------------- run
def run() -> pd.DataFrame:
    if "--status" in sys.argv:
        status()
        return pd.DataFrame()
    wait = "--wait" in sys.argv
    all_regions = _all_regions()
    frames, spent = [], 0

    for i, (country, region, coords) in enumerate(all_regions, 1):
        print(f"[{i}/{len(all_regions)}] {country} - {region}")
        while True:
            try:
                daily, cost = get_region_daily(country, region, coords, spent)
                spent += cost
                frames.append(region_monthly(daily, country, region, coords))
                break
            except RateLimitStop as e:
                if wait:
                    print(f"  Limit reached ({e}). Sleeping ~61 min, then continuing...")
                    time.sleep(61 * 60)
                    spent = 0
                    continue
                print(f"\nStopping: {e}.\n"
                      f"{len(frames)}/{len(all_regions)} regions are cached in {DAILY_CACHE_DIR}.\n"
                      f"Nothing is lost - re-run in about an hour (or use --wait) and it resumes.")
                return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    # Derived from the cache, so a timestamped copy per run would only add clutter.
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"[open_meteo_weather_monthly] wrote {len(df):,} rows -> {OUT_PATH.name}")
    print(f"Done. Estimated API calls used this run: ~{spent}.")
    return df


if __name__ == "__main__":
    run()
