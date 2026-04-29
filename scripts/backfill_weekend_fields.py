#!/usr/bin/env python3
"""
Box Office Jedi — Weekend File Backfill
=========================================
Walks every `data/weekends/*.json` chart file and corrects two fields that
the original scraper got wrong on a non-trivial number of weekends:

  1. is_new   — was True for any film not in the *immediately preceding*
                weekend's chart, which incorrectly flagged re-releases,
                limited expansions, and films that fell off and came back.
                Corrected rule: `is_new = True` iff this is the film's
                first ever appearance in our entire weekend archive.

  2. total_gross — was sometimes 0 because the yearly chart fallback
                missed titles (curly apostrophes, slight variants). We
                now compute a running total per movie_url across every
                prior weekend (inclusive of the current one), and only
                overwrite the file's value when it's currently 0.

Run (one-off):
    python3 scripts/backfill_weekend_fields.py
    python3 scripts/backfill_weekend_fields.py --dry-run

The script is idempotent — re-running it does not corrupt anything.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict


WEEKENDS_DIR = "data/weekends"


def normalize_title(s: str) -> str:
    return (s or "").strip()


def title_key(s: str) -> str:
    """Lowercase + strip non-alphanumeric for fuzzy title matching."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def film_key(row, url_for_title=None):
    """Same merge rule used elsewhere: prefer movie_url; fall back to a
    cached url-by-title (for weekends where the scraper dropped the URL);
    finally fall back to a normalized title."""
    url = (row.get("movie_url") or "").strip()
    if url:
        return ("url", url)
    tk = title_key(row.get("title"))
    if url_for_title and tk in url_for_title:
        return ("url", url_for_title[tk])
    return ("title", tk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change without writing files")
    ap.add_argument("--only-is-new", action="store_true",
                    help="Backfill only is_new (skip total_gross)")
    ap.add_argument("--only-totals", action="store_true",
                    help="Backfill only total_gross (skip is_new)")
    ap.add_argument("--totals-from-year", type=int, default=2026,
                    help="Only backfill total_gross for weekend files >= this "
                         "year (default 2026). Older years often have spotty "
                         "weekend coverage, so summing weekend grosses misses "
                         "weekday revenue and post-drop-off runs.")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(WEEKENDS_DIR, "*.json")))
    files = [f for f in files
             if os.path.basename(f) not in ("index.json",)]

    print(f"Scanning {len(files)} weekend files...")

    # Pass 1: build (a) title -> first non-empty movie_url cache
    #             (b) film_key -> first weekend date_from where it appeared
    url_for_title = {}
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        for row in (data.get("chart") or []):
            tk = title_key(row.get("title"))
            url = (row.get("movie_url") or "").strip()
            if not tk or not url:
                continue
            if tk not in url_for_title:
                url_for_title[tk] = url

    first_seen = {}     # film_key -> earliest date_from seen
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        date_from = data.get("date_from") or ""
        if not date_from:
            continue
        for row in (data.get("chart") or []):
            t = normalize_title(row.get("title"))
            if not t or t.lower().startswith("reporting:"):
                continue
            key = film_key(row, url_for_title)
            if key not in first_seen or date_from < first_seen[key]:
                first_seen[key] = date_from

    print(f"  Indexed {len(first_seen)} unique films across the archive.")

    # Pass 2: walk in chronological order, maintaining running totals per film,
    # and rewrite is_new + total_gross on each row.
    files_by_date = sorted(files, key=lambda p: os.path.basename(p))
    running_total = defaultdict(int)   # film_key -> cumulative weekend gross

    is_new_changes = 0
    total_changes  = 0
    files_changed  = 0

    for path in files_by_date:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        date_from = data.get("date_from") or ""
        chart = data.get("chart") or []
        if not chart or not date_from:
            continue

        file_dirty = False

        for row in chart:
            t = normalize_title(row.get("title"))
            if not t or t.lower().startswith("reporting:"):
                continue
            key = film_key(row, url_for_title)

            # Running cumulative weekend gross for this film
            wknd_gross = row.get("weekend_gross") or 0
            running_total[key] += wknd_gross

            # ── 1. is_new correction ────────────────────────────
            # Only flip True → False (correcting films wrongly marked new
            # because they fell off the chart and came back). We don't
            # flip False → True because the start of our archive (2007)
            # would mass-flag films whose true debuts predate our data.
            if not args.only_totals:
                if row.get("is_new") and first_seen.get(key) != date_from:
                    row["is_new"] = False
                    is_new_changes += 1
                    file_dirty = True

            # ── 2. total_gross fill-in ─────────────────────────
            # Only overwrite when the file's value is 0/missing — preserves
            # any actual cumulative figure the scraper or yearly chart
            # successfully captured. Limited to recent years (default 2026+)
            # because older archives have spotty weekend coverage and
            # summing weekend grosses misses weekday revenue + drop-off runs.
            if not args.only_is_new:
                file_year = int(date_from[:4]) if date_from[:4].isdigit() else 0
                if file_year >= args.totals_from_year:
                    cur = row.get("total_gross") or 0
                    if running_total[key] > cur and cur == 0:
                        row["total_gross"] = running_total[key]
                        total_changes += 1
                        file_dirty = True

        if file_dirty:
            files_changed += 1
            if not args.dry_run:
                with open(path, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

    print()
    print(f"is_new flips:        {is_new_changes}")
    print(f"total_gross fills:   {total_changes}")
    print(f"files updated:       {files_changed}{' (DRY RUN)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
