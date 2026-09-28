"""
Extract coffee area/yield/production from the FAOSTAT bulk download
(a different host, bulks-faostat.fao.org, from the fenixservices.fao.org
lightweight API — use this version if fenixservices is unreachable).

Keeps the Flag column (data-quality indicator: official/estimated/
imputed/calculated) alongside Area/Year/Element/Unit/Value.
"""
import io
import zipfile

import pandas as pd
import requests

from config.settings import COUNTRIES, FAOSTAT_ITEM, START_YEAR, END_YEAR
from src.extract._utils import save_raw

BULK_URL = (
    "https://bulks-faostat.fao.org/production/"
    "Production_Crops_Livestock_E_All_Data_(Normalized).zip"
)


def run() -> pd.DataFrame:
    print("Downloading FAOSTAT bulk file (large — this can take a few minutes)...")
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

    keep_cols = ["Area", "Year", "Element", "Unit", "Value"]
    if "Flag" in df.columns:
        keep_cols.append("Flag")

    df = df[
        (df["Item"] == FAOSTAT_ITEM)
        & (df["Area"].isin(faostat_names))
        & (df["Element"].isin(["Yield", "Area harvested", "Production"]))
        & (df["Year"] >= START_YEAR)
        & (df["Year"] <= END_YEAR)
    ][keep_cols]

    save_raw(df, "faostat_coffee")
    return df


if __name__ == "__main__":
    run()