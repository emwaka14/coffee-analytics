"""
Run the pipeline in sensible groups, with one command.

  python -m src.pipeline                    weather (cheap top-up) -> transform -> load
  python -m src.pipeline --all              everything, incl. USDA/FAO/CPI and the seasonal outlook
  python -m src.pipeline --only outlook,build
  python -m src.pipeline --dry-run          show what would run
  python -m src.pipeline --all --wait       first-ever run: let the weather step sleep through
                                            Open-Meteo's hourly limit instead of stopping

Suggested cadence (matches how often each source actually changes):
  weather    weekly (or daily if you like; ~30 API calls once history is cached)
  outlook    monthly (ECMWF issues the seasonal forecast once a month)
  reference  when USDA publishes (coffee: ~June and ~December) or monthly, FAO/prices yearly
  build      after any of the above

This pipeline keeps its state in data/raw (files + the weather cache), so run it from ONE
persistent machine. A fresh CI runner has no cache or raw files, so it would re-pull all
weather history and rebuild the tables without USDA/FAO inputs.
"""
import argparse
import importlib
import sys

ORDER = ["reference", "weather", "outlook", "build"]
GROUPS = {
    "reference": ["src.extract.us_cpi", "src.extract.usda_psd",
                  "src.extract.faostat", "src.extract.faostat_prices"],
    "weather":   ["src.extract.open_meteo"],
    "outlook":   ["src.extract.open_meteo_seasonal"],
    "build":     ["src.transform.build_country_year_table", "src.load.to_postgres"],
}
DEFAULT = ["weather", "build"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="run every group")
    ap.add_argument("--only", help=f"comma list from: {', '.join(ORDER)}")
    ap.add_argument("--dry-run", action="store_true")
    # unknown flags (e.g. --wait) are left in sys.argv for open_meteo to read
    args, _ = ap.parse_known_args()

    if args.all:
        chosen = ORDER
    elif args.only:
        chosen = [g.strip() for g in args.only.split(",")]
        bad = [g for g in chosen if g not in GROUPS]
        if bad:
            sys.exit(f"Unknown group(s) {bad}. Choose from {ORDER}.")
    else:
        chosen = DEFAULT
    plan = [m for g in ORDER if g in chosen for m in GROUPS[g]]

    print("Plan:\n  " + "\n  ".join(plan))
    if args.dry_run:
        return
    for name in plan:
        print(f"\n===== {name} =====")
        result = importlib.import_module(name).run()
        if name == "src.extract.open_meteo" and (result is None or result.empty):
            sys.exit("\nWeather history is not complete yet (rate limit or --status run). "
                     "Stopping before transform/load so nothing is built on partial weather. "
                     "Re-run later, or add --wait.")
    print("\nPipeline finished.")


if __name__ == "__main__":
    main()
