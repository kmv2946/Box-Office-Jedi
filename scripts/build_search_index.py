"""
Box Office Jedi — Build search index
====================================
Merges all known movies from:
  * data/movies/*.json           (TMDB-enriched, has metadata + poster)
  * data/movie_weekends/index.json  (every film that ever appeared in a
                                     weekend chart — the wide net)

Output: data/search-index.json  — one compact JSON, ~400-600KB, formatted
as an array of [title, year, tmdb_id, has_tmdb] rows so the client-side
searcher can filter in a single pass.

Run from the repo root:
    python3 scripts/build_search_index.py
"""
import json, os, glob, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

# TMDB-enriched movies — carry metadata + tmdb_id
tmdb_by_title = {}
for path in glob.glob("data/movies/*.json"):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    t = d.get("title")
    if not t: continue
    year = (d.get("release_date") or "")[:4] or None
    tmdb_by_title[t.lower()] = {
        "title":  t,
        "year":   year,
        "tmdb_id": d.get("tmdb_id"),
    }

# Weekend archive — every movie that ever charted. No metadata but plenty of titles.
arch_titles = {}
try:
    idx = json.load(open("data/movie_weekends/index.json"))
    for key, title in (idx.get("titles") or {}).items():
        # Pull a year from a per-movie file's opening_date
        # (that's the earliest weekend we've seen them in)
        try:
            m = json.load(open(f"data/movie_weekends/{key}.json"))
            year = (m.get("opening_date") or "")[:4] or None
        except Exception:
            year = None
        lk = title.lower()
        # Prefer TMDB entries over archive-only ones
        if lk not in tmdb_by_title:
            arch_titles[lk] = {"title": title, "year": year, "tmdb_id": None}
except FileNotFoundError:
    pass

# Combine, sorted by title
rows = []
for lk, d in tmdb_by_title.items():
    rows.append([d["title"], d["year"], d["tmdb_id"], True])
for lk, d in arch_titles.items():
    rows.append([d["title"], d["year"], None, False])

rows.sort(key=lambda r: (r[0] or "").lower())

# Write as a compact JSON
out_path = "data/search-index.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "updated": "now",
        "count":   len(rows),
        "rows":    rows,
    }, f, ensure_ascii=False, separators=(",", ":"))

size = os.path.getsize(out_path) / 1024
print(f"wrote {out_path}")
print(f"  total rows:      {len(rows):>6,}")
print(f"  tmdb-backed:     {sum(1 for r in rows if r[3]):>6,}")
print(f"  archive-only:    {sum(1 for r in rows if not r[3]):>6,}")
print(f"  file size (KB):  {size:>6,.1f}")
