"""
Box Office Jedi — Build search index
====================================
Merges all known movies from:
  * data/movies/*.json                       (TMDB-enriched, has tmdb_id)
  * data/movie_weekends_shards/index.json    (every film that ever appeared
                                              in a weekend chart — the wide
                                              net; titles dict is keyed by
                                              slug-with-year so same-titled
                                              films across years stay distinct)

Output: data/search-index.json — one compact JSON, ~400-600KB, formatted
as an array of [title, year, tmdb_id, has_tmdb] rows so the client-side
searcher can filter in a single pass.

Crucially: dedup is by (title.lower(), year) — NOT just title — so reboots
and same-titled films across decades (Moana 2016 vs 2026, Scary Movie 2000
vs 2026, Scream 1996 vs 2023, etc.) appear as separate search results.

Run from the repo root:
    python3 scripts/build_search_index.py
"""
import json, os, glob, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)


def year_from_slug(slug):
    """Pull a 4-digit year off the end of a slug like 'moana-2016'."""
    m = re.search(r"-(\d{4})$", slug or "")
    return m.group(1) if m else None


# ── TMDB-enriched movies (carry tmdb_id) ────────────────────────────────────
# Key by (title.lower(), year) so e.g. two films called "Moana" don't collide.
tmdb_by_key = {}
for path in glob.glob("data/movies/*.json"):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    t = d.get("title")
    if not t:
        continue
    year = (d.get("release_date") or "")[:4] or None
    key = (t.lower(), year)
    tmdb_by_key[key] = {
        "title":  t,
        "year":   year,
        "tmdb_id": d.get("tmdb_id"),
    }

# ── Weekend archive (no metadata, but the widest net of titles) ─────────────
# The new shard index keys by slug like "moana-2016" — year is encoded in
# the slug itself, so dedup by (title, year) keeps reboots separate.
arch_by_key = {}
try:
    idx = json.load(open("data/movie_weekends_shards/index.json"))
    titles_map = idx.get("titles") or {}
    for slug, title in titles_map.items():
        year = year_from_slug(slug)
        key = (title.lower(), year)
        # Prefer TMDB entries when both sources have the same key
        if key in tmdb_by_key:
            continue
        # Among archive-only entries, first one wins (slugs are unique
        # so this is deterministic)
        if key not in arch_by_key:
            arch_by_key[key] = {"title": title, "year": year, "tmdb_id": None}
except FileNotFoundError:
    pass

# ── Manual overrides (upcoming/recent films we've populated by hand) ─────────
# These are films that haven't yet appeared in any weekend chart but have
# entries in data/movie_meta_overrides.json. Without this source they'd be
# unsearchable until release. Same (title, year) dedup applies.
override_by_key = {}
try:
    overrides = json.load(open("data/movie_meta_overrides.json"))
    for slug, entry in overrides.items():
        if slug.startswith("_") or not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not title:
            continue
        year = entry.get("year")
        year_str = str(year) if year else year_from_slug(slug)
        key = (title.lower(), year_str)
        # Skip if any other source already has it
        if key in tmdb_by_key or key in arch_by_key:
            continue
        override_by_key[key] = {"title": title, "year": year_str, "tmdb_id": None}
except FileNotFoundError:
    pass

# ── Combine, sort by (title, year ascending) ────────────────────────────────
rows = []
for key, d in tmdb_by_key.items():
    rows.append([d["title"], d["year"], d["tmdb_id"], True])
for key, d in arch_by_key.items():
    rows.append([d["title"], d["year"], None, False])
for key, d in override_by_key.items():
    rows.append([d["title"], d["year"], None, False])

# Sort: title (case-insensitive) then year ascending so older releases come
# first when listing same-titled films.
rows.sort(key=lambda r: ((r[0] or "").lower(), int(r[1]) if r[1] and r[1].isdigit() else 0))

# ── Write compact JSON ──────────────────────────────────────────────────────
out_path = "data/search-index.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "updated": "now",
        "count":   len(rows),
        "rows":    rows,
    }, f, ensure_ascii=False, separators=(",", ":"))

size = os.path.getsize(out_path) / 1024
# Count duplicate-title (i.e. same title across multiple years) for the log
title_counts = {}
for r in rows:
    title_counts[(r[0] or "").lower()] = title_counts.get((r[0] or "").lower(), 0) + 1
dupes = sum(1 for n in title_counts.values() if n > 1)
dupe_rows = sum(n for n in title_counts.values() if n > 1)

print(f"wrote {out_path}")
print(f"  total rows:                {len(rows):>6,}")
print(f"  tmdb-backed:               {sum(1 for r in rows if r[3]):>6,}")
print(f"  archive-only:              {sum(1 for r in rows if not r[3]):>6,}")
print(f"  same-title across years:   {dupes:>6,} titles, {dupe_rows:>6,} rows")
print(f"  file size (KB):            {size:>6,.1f}")
