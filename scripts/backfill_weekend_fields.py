#!/usr/bin/env python3
"""
Box Office Jedi — Weekend File Backfill
=========================================
Walks every `data/weekends/*.json` chart file and corrects two fields the
original scraper left blank or wrong on many weekends.

  1. is_new   — was True for any film not in the *immediately preceding*
                weekend's chart, which incorrectly flagged re-releases,
                limited expansions, and films that fell off and came
                back. Corrected rule: `is_new = True` iff this is the
                film's first ever appearance in our entire weekend
                archive.

  2. weeks_in_release — typically 0 in scraped files because The Numbers
                doesn't always expose the "Days in Release" column the
                column-mapper expects. Computed here as the number of
                distinct weekends from the film's first appearance
                through and including this one.

This script does NOT touch total_gross. That field can only be filled
correctly by a real scrape against The Numbers — see
scripts/rescrape_missing_totals.py for that.

Run (one-off, idempotent):
    python3 scripts/backfill_weekend_fields.py
    python3 scripts/backfill_weekend_fields.py --dry-run
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


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

    # Pass 2: walk in chronological order and rewrite is_new + weeks on each row.
    files_by_date = sorted(files, key=lambda p: os.path.basename(p))

    is_new_changes = 0
    weeks_changes  = 0
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

            # ── 1. is_new correction ────────────────────────────
            # Only flip True → False (correcting films wrongly marked new
            # because they fell off the chart and came back). We don't
            # flip False → True because the start of our archive (2007)
            # would mass-flag films whose true debuts predate our data.
            if row.get("is_new") and first_seen.get(key) != date_from:
                row["is_new"] = False
                is_new_changes += 1
                file_dirty = True

            # ── 2. weeks_in_release ────────────────────────────
            # Number of weekends from the film's first appearance through
            # this one. Opening weekend = 1, second weekend = 2, etc.
            # Only overwrite when the file's value is 0/missing.
            cur_weeks = row.get("weeks_in_release") or 0
            if cur_weeks <= 0:
                first_dt_str = first_seen.get(key)
                if first_dt_str:
                    try:
                        d_first = datetime.strptime(first_dt_str, "%Y-%m-%d")
                        d_now   = datetime.strptime(date_from, "%Y-%m-%d")
                        delta_days = (d_now - d_first).days
                        wk = max(1, (delta_days // 7) + 1)
                        row["weeks_in_release"] = wk
                        weeks_changes += 1
                        file_dirty = True
                    except Exception:
                        pass

        if file_dirty:
            files_changed += 1
            if not args.dry_run:
                with open(path, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

    print()
    print(f"is_new flips:        {is_new_changes}")
    print(f"weeks_in_release:    {weeks_changes}")
    print(f"files updated:       {files_changed}{' (DRY RUN)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
