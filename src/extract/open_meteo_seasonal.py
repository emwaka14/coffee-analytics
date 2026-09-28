"""
Pull the seasonal weather outlook (up to ~7 months ahead) for each coffee
region, from Open-Meteo's Seasonal Forecast API (ECMWF SEAS5).

This is a forward-looking climate *outlook*, not a precise forecast — the
data is explicitly not bias-corrected, and should be read as "wetter/drier,
warmer/cooler than the historical average," not an exact prediction. Good
for a "climate risk outlook" panel; don't present it as a yield forecast.

No API key needed. Free for non-commercial use.
"""
import time
from datetime import date

import pandas as pd
import requests

from config.settings import REGIONS
from src.extract._utils import save_raw

API_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"

REQUEST_DELAY_SEC = 2
MAX_RETRIES = 5
BACKOFF_BASE_SEC = 10


def fetch_region_outlook(lat: float, lon: float) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        # mean value and anomaly vs model climatology, monthly resolution
        "monthly": "temperature_2m_mean,temperature_2m_anomaly,"
                    "precipitation_mean,precipitation_anomaly",
        "forecast_days": 217,  # ~7 months ahead
    }

    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(API_URL, params=params, timeout=120)
        if resp.status_code == 200:
            break
        if resp.status_code == 429:
            wait = BACKOFF_BASE_SEC * attempt
            print(f"  Rate limited, waiting {wait}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    else:
        raise RuntimeError(f"Gave up on ({lat}, {lon}) after {MAX_RETRIES} retries.")

    # NOTE: confirm the exact response key ("monthly" vs something else) and
    # the field names against a live response — Open-Meteo's seasonal
    # endpoint response shape wasn't directly verifiable while writing this.
    payload = resp.json()
    if "monthly" not in payload:
        raise RuntimeError(f"Unexpected seasonal response keys {list(payload)} - "
                           f"check the Open-Meteo docs and update this parser.")
    monthly = pd.DataFrame(payload["monthly"])
    monthly["time"] = pd.to_datetime(monthly["time"])

    time.sleep(REQUEST_DELAY_SEC)
    return monthly


def run() -> pd.DataFrame:
    # Stamp every pull with its issue date so forecasts accumulate in the DB
    # and can be backtested against realised outcomes later.
    issue_date = date.today().isoformat()
    rows = []
    for country, regions in REGIONS.items():
        for region_name, coords in regions.items():
            print(f"Fetching seasonal outlook for {country} — {region_name}...")
            outlook = fetch_region_outlook(coords["lat"], coords["lon"])
            outlook["country_name"] = country
            outlook["region"] = region_name
            outlook["issue_date"] = issue_date
            rows.append(outlook)

    df = pd.concat(rows, ignore_index=True)
    save_raw(df, "open_meteo_seasonal_outlook")
    return df


if __name__ == "__main__":
    run()
