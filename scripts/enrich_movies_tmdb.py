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


SHARDS_DIR = os.path.join(DATA_DIR, "movies_meta_shards")


def shard_letter(key: str) -> str:
    """First letter of slug → shard. Non-alphabetic → '_'."""
    if not key:
        return "_"
    c = key[0].lower()
    return c if "a" <= c <= "z" else "_"


# In-memory shard cache so we read each shard at most once per run, then
# flush dirty shards at the end (or every N films).
_SHARD_CACHE: dict = {}
_DIRTY_SHARDS: set = set()


def load_shard(letter: str) -> dict:
    if letter in _SHARD_CACHE:
        return _SHARD_CACHE[letter]
    path = os.path.join(SHARDS_DIR, f"{letter}.json")
    try:
        with open(path) as f:
            d = json.load(f)
            _SHARD_CACHE[letter] = d.get("entries") or {}
            return _SHARD_CACHE[letter]
    except (FileNotFoundError, json.JSONDecodeError):
        _SHARD_CACHE[letter] = {}
        return _SHARD_CACHE[letter]


def write_shard(letter: str):
    os.makedirs(SHARDS_DIR, exist_ok=True)
    path = os.path.join(SHARDS_DIR, f"{letter}.json")
    entries = _SHARD_CACHE.get(letter) or {}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "updated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "letter":  letter,
            "count":   len(entries),
            "entries": entries,
        }, f, ensure_ascii=False)


def flush_dirty_shards():
    for letter in list(_DIRTY_SHARDS):
        write_shard(letter)
    _DIRTY_SHARDS.clear()


def existing_curated_entry(key: str) -> bool:
    """True if either the legacy per-file or the new shard already has this slug."""
    if os.path.exists(os.path.join(DATA_DIR, "movies_meta", key + ".json")):
        return True
    shard = load_shard(shard_letter(key))
    return key in shard


# Legacy alias retained for any older callers
def existing_curated_file(key: str) -> bool:
    return existing_curated_entry(key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year",  type=int, default=None,
                    help="Only enrich films from this opening year")
    ap.add_argument("--since", default="",
                    help="Only enrich films opening on or after YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after enriching this many titles (0 = no cap)")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-fetch even if a meta entry already exists. "
                         "Hand-curated entries (any meta NOT tagged "
                         "_source: tmdb-enrich) are still skipped — pass "
                         "--force-overwrite to clobber those too.")
    ap.add_argument("--force-overwrite", action="store_true",
                    help="Allow --refresh to also overwrite hand-curated entries.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List the titles that would be enriched, then exit")
    args = ap.parse_args()

    if TMDB_API_KEY == "YOUR_API_KEY_HERE":
        print("ERROR: No TMDB API key set. Export TMDB_API_KEY first.")
        sys.exit(1)

    # Collect candidates from the sharded weekend archives. Falls back to
    # the legacy per-file dir if the shards haven't been built yet (first run
    # on an old branch).
    candidates = []
    seen_keys = set()
    weekend_shards = sorted(glob.glob(
        os.path.join(DATA_DIR, "movie_weekends_shards", "*.json")))
    weekend_per_file = sorted(glob.glob(
        os.path.join(DATA_DIR, "movie_weekends", "*.json")))

    def consider(key, title, opening):
        if not title or not key:
            return
        if key in seen_keys:
            return
        seen_keys.add(key)
        if args.year and opening[:4] != str(args.year):
            return
        if args.since and opening < args.since:
            return

        # Existing-entry check. Skip unless --refresh is explicit. And even
        # with --refresh, leave hand-curated entries alone unless the caller
        # ALSO passed --force-overwrite (rare, intentional).
        existing = None
        shard = load_shard(shard_letter(key))
        if key in shard:
            existing = shard[key]
        elif os.path.exists(os.path.join(DATA_DIR, "movies_meta", key + ".json")):
            try:
                with open(os.path.join(DATA_DIR, "movies_meta", key + ".json")) as f:
                    existing = json.load(f)
            except Exception:
                existing = None
        if existing and not args.refresh:
            return
        if existing and args.refresh and not args.force_overwrite:
            src = (existing.get("_source") or "manual").strip().lower()
            if src != "tmdb-enrich":
                return
        candidates.append((key, title, opening))

    if weekend_shards:
        print(f"Scanning {len(weekend_shards)} weekend shard files...")
        for path in weekend_shards:
            if os.path.basename(path) == "index.json":
                continue
            try:
                with open(path) as f:
                    d = json.load(f)
            except Exception:
                continue
            for key, payload in (d.get("entries") or {}).items():
                consider(key, payload.get("title") or "",
                         payload.get("opening_date") or "")
    else:
        print(f"Scanning {len(weekend_per_file)} per-movie weekend files (legacy)...")
        for path in weekend_per_file:
            if os.path.basename(path) == "index.json":
                continue
            try:
                with open(path) as f:
                    d = json.load(f)
            except Exception:
                continue
            key = (d.get("key") or os.path.basename(path).replace(".json", ""))
            consider(key, d.get("title") or "", d.get("opening_date") or "")

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

    os.makedirs(SHARDS_DIR, exist_ok=True)

    enriched = 0
    skipped  = 0
    failed   = 0

    for i, (key, title, opening) in enumerate(candidates, 1):
        # Prefer the year embedded in the slug (e.g., "michael-2026") — the
        # aggregate writes the actual film's release year there. Fall back
        # to opening_date's year for slug-less legacy entries.
        year = None
        m = re.search(r"-(\d{4})$", key)
        if m:
            year = int(m.group(1))
        if not year and opening[:4].isdigit():
            year = int(opening[:4])
        result = search_tmdb(title, year)
        if not result:
            print(f"  [{i}/{len(candidates)}] {title!r} ({year}) — no TMDB match")
            failed += 1
            continue
        detail = fetch_movie_detail(result["id"])
        if not detail:
            failed += 1
            continue

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
        # Write into the shard (Cloudflare Pages caps at 20k files; per-film
        # files would re-explode the count, so we batch into letter shards).
        letter = shard_letter(key)
        shard = load_shard(letter)
        shard[key] = meta
        _DIRTY_SHARDS.add(letter)

        enriched += 1
        # Flush periodically so a long run that gets killed still leaves a
        # valid set of shard files behind.
        if i % 100 == 0:
            flush_dirty_shards()
            print(f"  Progress: {i}/{len(candidates)}  enriched={enriched}  failed={failed}")

    flush_dirty_shards()
    print()
    print(f"Done. enriched={enriched}  skipped={skipped}  failed={failed}")


if __name__ == "__main__":
    main()
