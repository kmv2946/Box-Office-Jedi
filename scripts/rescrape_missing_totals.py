#!/usr/bin/env python3
"""
Box Office Jedi — Re-scrape weekends with missing Total Gross
=============================================================
Walks every `data/weekends/*.json` file. For any weekend where Total Gross
is 0 for every (or nearly every) film, calls scrape_the_numbers.py with
--force to re-fetch that date's chart from The Numbers.

The Numbers' weekend chart pages reliably include a "Total Gross" column
for every weekend (verified visually). A blank-totals weekend file means
the column got dropped at scrape time — usually due to a header layout
the column-mapper didn't recognize. The hardened mapper in
scrape_the_numbers.py should now correctly find the column.

Usage:
    python3 scripts/rescrape_missing_totals.py            # do it
    python3 scripts/rescrape_missing_totals.py --dry-run  # just list
    python3 scripts/rescrape_missing_totals.py --since 2020-01-01
                                                          # limit to recent

Run from the repo root. This makes one HTTP request per affected
weekend with a 1.5-second delay between calls (built into the scraper).
A full re-scrape of every blank-totals weekend takes a while — use
--since to stage it in batches if needed.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

WEEKENDS_DIR = "data/weekends"
SCRAPER      = "scripts/scrape_the_numbers.py"


def is_blank_totals(path: str) -> bool:
    """A weekend is 'blank totals' if every chart row has total_gross == 0
    (or missing). We require the file to have at least 5 rows so we don't
    re-scrape weekends with genuinely tiny charts."""
    try:
        with open(path) as f:
            d = json.load(f)
    except Exception:
        return False
    chart = d.get("chart") or []
    if len(chart) < 5:
        return False
    nz = sum(1 for r in chart if (r.get("total_gross") or 0) > 0)
    return nz == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List affected weekends without scraping")
    ap.add_argument("--since", default="",
                    help="Only re-scrape weekends with date_from >= this "
                         "YYYY-MM-DD (default: all)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after re-scraping this many weekends "
                         "(0 = no limit)")
    args = ap.parse_args()

    files = sorted(
        p for p in glob.glob(os.path.join(WEEKENDS_DIR, "*.json"))
        if os.path.basename(p) != "index.json"
    )

    affected = []
    for path in files:
        date = os.path.basename(path).replace(".json", "")
        if args.since and date < args.since:
            continue
        if is_blank_totals(path):
            affected.append(date)

    print(f"Found {len(affected)} weekend files with no Total Gross data.")
    if args.since:
        print(f"  (filtered to >= {args.since})")
    if not affected:
        return

    if args.dry_run:
        for d in affected:
            print(f"  would re-scrape: {d}")
        return

    if args.limit:
        affected = affected[-args.limit:]   # most recent first
        print(f"  --limit {args.limit} → re-scraping the {len(affected)} most recent")

    succeeded, failed = 0, 0
    for i, d in enumerate(affected, 1):
        print(f"\n[{i}/{len(affected)}] re-scraping {d}")
        cmd = [
            sys.executable, SCRAPER,
            "--mode", "weekend",
            "--date", d,
            "--force",
        ]
        try:
            r = subprocess.run(cmd, check=False)
            if r.returncode == 0:
                succeeded += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break

    print(f"\nDone. succeeded={succeeded}  failed={failed}")


if __name__ == "__main__":
    main()
