"""
Extract farmgate (producer) coffee prices from FAOSTAT's Prices domain,
via the bulk-download file — the same reliable, keyless approach as
faostat.py. The lightweight query API (fenixservices.fao.org) is not used
here: it's both currently down and, per FAOSTAT's own docs, now requires
a registered API key even when it's up. Bulk downloads need neither.

NOTE: this filename follows the same pattern confirmed for other FAOSTAT
domains (e.g. Inputs_LandUse_E_All_Data_(Normalized).zip for Land Use),
but wasn't verified directly against a live response for Prices — if this
404s, get the exact link from the "Bulk Download" > "All Data Normalized"
link on https://www.fao.org/faostat/en/#data/PP and update BULK_URL below.

Coverage starts around 1991 — don't expect rows before that.
"""
import io
import zipfile

import pandas as pd
import requests

from config.settings import COUNTRIES, FAOSTAT_ITEM, START_YEAR, END_YEAR
from src.extract._utils import save_raw

BULK_URL = "https://bulks-faostat.fao.org/production/Prices_E_All_Data_(Normalized).zip"

ELEMENT = "Producer Price (USD/tonne)"  # NOTE: verify exact label once the
                                          # file downloads — print
                                          # df["Element"].unique() if this
                                          # filter returns nothing.


def run() -> pd.DataFrame:
    print("Downloading FAOSTAT Prices bulk file...")
    resp = requests.get(BULK_URL, timeout=600)
    resp.raise_for_status()

    faostat_names = [info["faostat_name"] for info in COUNTRIES.values()]

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_name = next(
            n for n in z.namelist()
            if n.endswith(".csv")
            and not any(x in n for x in ["Flags", "ItemCodes", "AreaCodes", "Elements", "Symbols"])
        )
        with z.open(csv_name) as f:
            df = pd.read_csv(f, encoding="latin-1", low_memory=False)

    # The Prices file can carry monthly rows too; keep annual values only,
    # otherwise the merge downstream multiplies rows.
    if "Months" in df.columns:
        df = df[df["Months"].astype(str).str.contains("Annual", case=False, na=False)]

    keep_cols = ["Area", "Year", "Element", "Unit", "Value"]
    if "Flag" in df.columns:
        keep_cols.append("Flag")

    df = df[
        (df["Item"] == FAOSTAT_ITEM)
        & (df["Area"].isin(faostat_names))
        & df["Element"].str.contains("Producer Price", case=False, na=False)
        & df["Element"].str.contains("USD", case=False, na=False)
        & (df["Year"] >= START_YEAR)
        & (df["Year"] <= END_YEAR)
    ][keep_cols]

    if df.empty:
        print(f"  No rows matched. Check ELEMENT above against the real "
              f"values in the file — try printing pd.read_csv(...)['Element'].unique().")

    df = df.drop_duplicates(subset=["Area", "Year"], keep="last")
    df = df.rename(columns={"Value": "producer_price_usd_per_tonne"})
    save_raw(df, "faostat_producer_prices")
    return df


if __name__ == "__main__":
    run()
