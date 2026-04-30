#!/usr/bin/env python3
"""
Box Office Jedi — Bulk TMDB Enrichment by Title
=================================================
Walks every per-movie weekend archive (`data/movie_weekends/*.json`),
searches TMDB for the title (using release year as a disambiguator), and
writes the resulting metadata to `data/movies_meta/{key}.json` so the
movie profile page picks it up.

The output file is the same shape as our hand-curated overrides — same
field names — so manual edits and TMDB enrichment can coexist. Manual
edits ALWAYS win (this script never overwrites a curated file).

Why slug-keyed instead of TMDB-id-keyed:
    The movie profile page resolves by normalized title slug. TMDB IDs
    are useful but only available after we look the film up. Saving by
    slug means lookup is instant on the front end.

What we capture per film:
    poster_url, mpaa, runtime, genres, budget, revenue, release_date,
    distributor (best effort from production_companies — TMDB doesn't
    expose theatrical distributor cleanly, so we leave it blank when
    unsure to avoid wrong data), tmdb_id (so future targeted refreshes
    can hit the by-id endpoint).

Usage:
    export TMDB_API_KEY="..."
    python3 scripts/enrich_movies_tmdb.py                   # all titles
    python3 scripts/enrich_movies_tmdb.py --year 2026       # one year
    python3 scripts/enrich_movies_tmdb.py --since 2020-01-01
    python3 scripts/enrich_movies_tmdb.py --limit 50        # cap the run
    python3 scripts/enrich_movies_tmdb.py --refresh         # re-fetch even
                                                            # if file exists
    python3 scripts/enrich_movies_tmdb.py --dry-run         # list only

The TMDB free tier rate-limits at ~40 req/10s, and each enrichment makes
2 HTTP calls (search + detail) — so plan for ~5 titles per second tops.
A full archive enrichment for ~15k titles takes ~50 minutes.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

# Reuse the helpers from tmdb_api.py
THIS_DIR = os.path.dirname(__file__)
sys.path.insert(0, THIS_DIR)
from tmdb_api import (    # type: ignore
    tmdb_get, poster_url, fetch_movie_detail, TMDB_API_KEY, DATA_DIR,
)


def norm_title(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def search_tmdb(title: str, year: int | None = None) -> dict | None:
    """Search TMDB for a title. Returns the best match dict or None.
    A "best match" is the first result whose release_date year matches
    `year` (when provided), else the first result overall."""
    params = {"query": title, "include_adult": "false"}
    if year:
        params["primary_release_year"] = year
    data = tmdb_get("/search/movie", params)
    if not data or not data.get("results"):
        # Retry without the year constraint — TMDB sometimes mis-tags release year
        if year:
            data = tmdb_get("/search/movie", {"query": title, "include_adult": "false"})
        if not data or not data.get("results"):
            return None
    results = data["results"]
    if year:
        for r in results:
            rd = (r.get("release_date") or "")
            if rd[:4] == str(year):
                return r
    return results[0] if results else None


def existing_curated_file(key: str) -> bool:
    return os.path.exists(os.path.join(DATA_DIR, "movies_meta", key + ".json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year",  type=int, default=None,
                    help="Only enrich films from this opening year")
    ap.add_argument("--since", default="",
                    help="Only enrich films opening on or after YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after enriching this many titles (0 = no cap)")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-fetch even if a curated meta file already exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="List the titles that would be enriched, then exit")
    args = ap.parse_args()

    if TMDB_API_KEY == "YOUR_API_KEY_HERE":
        print("ERROR: No TMDB API key set. Export TMDB_API_KEY first.")
        sys.exit(1)

    weekend_files = sorted(glob.glob(os.path.join(DATA_DIR, "movie_weekends", "*.json")))
    print(f"Scanning {len(weekend_files)} per-movie weekend archives...")

    candidates = []
    for path in weekend_files:
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        title = d.get("title") or ""
        opening = d.get("opening_date") or ""
        key = (d.get("key") or os.path.basename(path).replace(".json", ""))
        if not title:
            continue
        if args.year and opening[:4] != str(args.year):
            continue
        if args.since and opening < args.since:
            continue
        if not args.refresh and existing_curated_file(key):
            continue
        candidates.append((key, title, opening))

    print(f"  {len(candidates)} titles to enrich.")

    if args.limit:
        candidates = candidates[:args.limit]
        print(f"  --limit {args.limit} → only the first {len(candidates)}")

    if args.dry_run:
        for key, title, opening in candidates[:50]:
            print(f"    {opening:>10s}  {title}")
        if len(candidates) > 50:
            print(f"    ... and {len(candidates) - 50} more")
        return

    out_dir = os.path.join(DATA_DIR, "movies_meta")
    os.makedirs(out_dir, exist_ok=True)
    cache_dir = os.path.join(DATA_DIR, "movies")
    os.makedirs(cache_dir, exist_ok=True)

    enriched = 0
    skipped  = 0
    failed   = 0

    for i, (key, title, opening) in enumerate(candidates, 1):
        year = int(opening[:4]) if opening[:4].isdigit() else None
        result = search_tmdb(title, year)
        if not result:
            print(f"  [{i}/{len(candidates)}] {title!r} ({year}) — no TMDB match")
            failed += 1
            continue
        detail = fetch_movie_detail(result["id"])
        if not detail:
            failed += 1
            continue

        # Save the full TMDB detail by id (parallel to existing /movies/ store)
        with open(os.path.join(cache_dir, f"{result['id']}.json"), "w") as f:
            json.dump(detail, f, indent=2, ensure_ascii=False)

        # Write the curated-meta-style override file
        meta = {
            "_source": "tmdb-enrich",
            "title":          detail.get("title") or title,
            "tmdb_id":        detail.get("tmdb_id"),
            "release_date":   detail.get("release_date") or opening or "",
            "runtime":        detail.get("runtime") or 0,
            "genres":         detail.get("genres") or [],
            "mpaa":           detail.get("mpaa") or "",
            "budget":         detail.get("budget") or 0,
            "revenue":        detail.get("revenue") or 0,
            "poster_url":     detail.get("poster_url") or "",
            "backdrop_url":   detail.get("backdrop_url") or "",
            "tagline":        detail.get("tagline") or "",
            "overview":       detail.get("overview") or "",
        }
        with open(os.path.join(out_dir, f"{key}.json"), "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        enriched += 1
        if i % 25 == 0:
            print(f"  Progress: {i}/{len(candidates)}  enriched={enriched}  failed={failed}")

    print()
    print(f"Done. enriched={enriched}  skipped={skipped}  failed={failed}")


if __name__ == "__main__":
    main()
