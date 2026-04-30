#!/usr/bin/env python3
"""
Box Office Jedi — Movie Totals Index Builder
==============================================
Walks every yearly archive (`data/years/*.json` + `data/yearly.json`) and
produces a single flat lookup:

    data/movie_totals.json
    {
      "updated": "...",
      "by_title": {
        "thedevilwearsprada":       {"year": 2006, "total_gross": 124740460,
                                     "distributor": "Fox", "rank": 11},
        "cars":                     {"year": 2006, "total_gross": 244082982,
                                     "distributor": "BV",  "rank": 3},
        ...
      }
    }

The movie profile page (`movie.html`) uses this as the authoritative
source for Domestic Total Gross. Why? Because the per-movie weekend
archive only has top-50 weekend grosses — summing those misses weekday
revenue and any weeks the film fell off the chart's tail. Yearly charts
are scraped from The Numbers' year-to-date page, which tracks the real
cumulative total straight through.

When two yearly charts disagree (e.g. a film carries over into the
next calendar year), the LARGEST total wins — that's the most up-to-date
post-run figure.

Run:
    python3 scripts/build_movie_totals_index.py
    python3 scripts/build_movie_totals_index.py --dry-run

Run automatically: see .github/workflows/update-data.yml
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime


DATA_DIR = "data"


def norm_title(s: str) -> str:
    """Lowercase + strip everything non-alphanumeric. Same convention used
    everywhere else (distributors.json, movies_meta/, movie_weekends/)."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sources = []
    sources.extend(sorted(glob.glob(os.path.join(DATA_DIR, "years", "*.json"))))
    sources.append(os.path.join(DATA_DIR, "yearly.json"))   # current year

    by_title = {}     # norm_title → {year, total_gross, distributor, rank}
    files_seen = 0
    rows_seen  = 0

    for path in sources:
        if not os.path.exists(path):
            continue
        d = load_json(path)
        if not d:
            continue
        year = d.get("year") or 0
        # Files like data/years/2006.json — derive year from filename if missing
        if not year:
            base = os.path.basename(path).replace(".json", "")
            if base[:4].isdigit():
                year = int(base[:4])
        rows = d.get("chart") or []
        if not rows:
            continue
        files_seen += 1
        for r in rows:
            title = r.get("title") or ""
            tot   = r.get("total_gross") or 0
            if not title or tot <= 0:
                continue
            key = norm_title(title)
            if not key:
                continue
            rows_seen += 1
            entry = {
                "title":       title,
                "year":        year,
                "total_gross": tot,
                "distributor": r.get("distributor", "") or "",
                "rank":        r.get("rank") or 0,
            }
            existing = by_title.get(key)
            # Keep the larger total_gross when a film carries across years.
            # Preserve the YEAR of the larger total too, so opening-year
            # films don't get retagged with a holdover year.
            if existing is None or tot > existing["total_gross"]:
                by_title[key] = entry

    payload = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "count":   len(by_title),
        "by_title": by_title,
    }

    out_path = os.path.join(DATA_DIR, "movie_totals.json")
    print(f"  Scanned {files_seen} yearly files, {rows_seen} rows.")
    print(f"  Indexed {len(by_title)} unique films.")
    if args.dry_run:
        # Show a few sample lookups so the user can sanity-check.
        for sample in ("cars", "thedevilwearsprada", "thedarkknight", "avatar"):
            v = by_title.get(sample)
            if v:
                print(f"    {sample:30s} → ${v['total_gross']:>13,}  ({v['year']})  {v['title']}")
        print("  (dry run — no file written)")
        return
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Wrote {out_path}")


if __name__ == "__main__":
    main()
