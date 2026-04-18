"""
Box Office Jedi — Aggregate Weekend Grosses per Movie
=====================================================
Reads every file in data/weekends/*.json and produces one compact JSON
per movie under data/movie_weekends/, plus a lightweight index.

    data/movie_weekends/index.json          — { key: title, ... }
    data/movie_weekends/<key>.json          — per-movie weekend data

Per-movie file shape:
    {
      "key":           "oppenheimer",
      "title":         "Oppenheimer",
      "opening_date":  "2023-07-21",
      "opening_gross": 82455420,
      "weekends": [
        { "n": 1, "date": "2023-07-21", "gross": 82455420,
          "rank": 2, "theaters": 3610, "total_gross": 82455420 },
        ...
      ]
    }

Why per-movie files: a single blob of all 15,000+ films is ~22 MB. Each
showdown page only needs 3–6 movies, so it fetches 3–6 tiny files (a few
KB each) instead of downloading the full catalog.

Key normalization: lowercase, alphanumeric only. "All At Once" and
"All at Once" collapse to the same key.

Run from the repo root:
    python3 scripts/aggregate_movie_weekends.py
"""

import json
import os
import re
import glob
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKENDS  = os.path.join(REPO_ROOT, "data", "weekends")
OUT_DIR   = os.path.join(REPO_ROOT, "data", "movie_weekends")


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def main():
    files = sorted(f for f in glob.glob(os.path.join(WEEKENDS, "*.json"))
                   if not f.endswith("index.json"))

    movies: dict = {}

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        date_from = d.get("date_from")
        if not date_from:
            continue
        for row in d.get("chart", []):
            t = row.get("title")
            if not t:
                continue
            key = norm_title(t)
            if not key:
                continue
            bucket = movies.setdefault(key, {"title": t, "_latest": "", "rows": []})
            if date_from > bucket["_latest"]:
                bucket["title"]   = t
                bucket["_latest"] = date_from
            bucket["rows"].append({
                "date":        date_from,
                "gross":       row.get("weekend_gross") or 0,
                "rank":        row.get("rank"),
                "theaters":    row.get("theaters"),
                "total_gross": row.get("total_gross"),
            })

    os.makedirs(OUT_DIR, exist_ok=True)

    # Write per-movie files + build index
    index = {}
    total_weekends = 0
    for key, b in movies.items():
        rows = sorted(b["rows"], key=lambda r: r["date"])
        seen = set()
        deduped = []
        for r in rows:
            if r["date"] in seen:
                continue
            seen.add(r["date"])
            deduped.append(r)
        weekends = []
        for n, r in enumerate(deduped, start=1):
            weekends.append({
                "n":           n,
                "date":        r["date"],
                "gross":       r["gross"],
                "rank":        r["rank"],
                "theaters":    r["theaters"],
                "total_gross": r["total_gross"],
            })
        if not weekends:
            continue
        movie = {
            "key":           key,
            "title":         b["title"],
            "opening_date":  weekends[0]["date"],
            "opening_gross": weekends[0]["gross"],
            "weekends":      weekends,
        }
        with open(os.path.join(OUT_DIR, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(movie, f, indent=1, ensure_ascii=False)
        index[key] = b["title"]
        total_weekends += len(weekends)

    # Small index file so clients can enumerate or verify a title exists
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated": datetime.utcnow().isoformat(),
            "count":   len(index),
            "titles":  index,
        }, f, indent=1, ensure_ascii=False)

    print("Wrote per-movie files to " + OUT_DIR)
    print("  movies:        {:>7,}".format(len(index)))
    print("  weekends in:   {:>7,}".format(total_weekends))
    # Sample sizes
    sample_keys = ["oppenheimer", "sinners", "hereditary"]
    for k in sample_keys:
        p = os.path.join(OUT_DIR, k + ".json")
        if os.path.exists(p):
            print("  sample size:   {:>7,} bytes  {}.json".format(os.path.getsize(p), k))


if __name__ == "__main__":
    main()
