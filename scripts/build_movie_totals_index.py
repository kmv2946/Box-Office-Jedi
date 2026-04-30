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

    by_title = {}     # plain title key  → entry  (most-recent / largest wins)
    by_slug  = {}     # slug (title-year) → entry  (always exact match)

    files_seen = 0
    rows_seen  = 0

    def url_year(url: str):
        if not url:
            return None
        m = re.search(r"\((\d{4})", url)
        return int(m.group(1)) if m else None

    for path in sources:
        if not os.path.exists(path):
            continue
        d = load_json(path)
        if not d:
            continue
        file_year = d.get("year") or 0
        if not file_year:
            base = os.path.basename(path).replace(".json", "")
            if base[:4].isdigit():
                file_year = int(base[:4])
        rows = d.get("chart") or []
        if not rows:
            continue
        files_seen += 1
        for r in rows:
            title = r.get("title") or ""
            tot   = r.get("total_gross") or 0
            if not title or tot <= 0:
                continue
            tk = norm_title(title)
            if not tk:
                continue
            # Prefer the year encoded in the row's movie_url (which actually
            # identifies the film) over the chart's calendar year — a film
            # released in late 2005 can be on the 2006 chart. Fall back to
            # the chart year when the movie_url is missing.
            row_year = url_year(r.get("movie_url")) or file_year or None
            slug_key = f"{tk}-{row_year}" if row_year else tk

            rows_seen += 1
            entry = {
                "title":       title,
                "year":        row_year or file_year,
                "total_gross": tot,
                "distributor": r.get("distributor", "") or "",
                "rank":        r.get("rank") or 0,
            }

            # Slug map: ALWAYS keeps the largest total for that exact film
            # (handles the same film appearing in multiple yearly charts as
            # a holdover — last year's run is the cumulative total).
            existing_slug = by_slug.get(slug_key)
            if existing_slug is None or tot > existing_slug["total_gross"]:
                by_slug[slug_key] = entry

            # Plain title map: when two different films share the title
            # (Michael 1996 vs 2026), the most-recent one wins so legacy
            # links resolve to the relevant current film.
            existing_plain = by_title.get(tk)
            if (existing_plain is None
                or (entry["year"] or 0) > (existing_plain["year"] or 0)
                or ((entry["year"] or 0) == (existing_plain["year"] or 0)
                    and tot > existing_plain["total_gross"])):
                by_title[tk] = entry

    payload = {
        "updated":  datetime.now().isoformat(timespec="seconds"),
        "count":    len(by_title),
        "by_title": by_title,    # plain key → most-recent film of that title
        "by_slug":  by_slug,     # slug (title-year) → exact film
    }

    out_path = os.path.join(DATA_DIR, "movie_totals.json")
    print(f"  Scanned {files_seen} yearly files, {rows_seen} rows.")
    print(f"  Indexed {len(by_title)} unique titles, {len(by_slug)} unique slug entries.")
    if args.dry_run:
        for sample in ("michael", "michael-1996", "michael-2026",
                       "cars", "thedevilwearsprada"):
            v = by_slug.get(sample) or by_title.get(sample)
            if v:
                print(f"    {sample:25s} → ${v['total_gross']:>13,}  ({v['year']})  {v['title']}")
        print("  (dry run — no file written)")
        return
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Wrote {out_path}")


if __name__ == "__main__":
    main()
