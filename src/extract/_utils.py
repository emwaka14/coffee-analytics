"""Small shared helpers so every extract script behaves the same way:
save raw, untouched, timestamped output — never overwrite silently."""
from datetime import datetime, timezone

import pandas as pd

from config.settings import RAW_DIR


def save_raw(df: pd.DataFrame, source: str) -> str:
    """Save a raw extract with a UTC timestamp so old pulls aren't lost.

    Also writes/overwrites a `<source>_latest.csv` pointer so transform
    scripts always have a stable filename to read from.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dated_path = RAW_DIR / f"{source}_{stamp}.csv"
    latest_path = RAW_DIR / f"{source}_latest.csv"

    df.to_csv(dated_path, index=False)
    df.to_csv(latest_path, index=False)

    print(f"[{source}] saved {len(df):,} rows -> {dated_path.name} (and _latest.csv)")
    return str(dated_path)
