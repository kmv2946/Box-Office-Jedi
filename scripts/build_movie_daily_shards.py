"""
Box Office Jedi — Aggregate Daily Grosses per Movie
====================================================
Reads every file in data/daily/*.json and produces one compact per-movie
daily history, sharded by first-letter, under data/movie_daily_shards/.
This is the daily-granularity counterpart to
data/movie_weekends_shards/ (see aggregate_movie_weekends.py) and exists
to power all-time charts that need single-day precision:
fastest-to-$X-million, top single-day grosses, top opening days, Friday
share of opening weekend, and holiday (e.g. Christmas) single-day records.

Per-movie entry shape (inside data/movie_daily_shards/<letter>.json):
    {
      "key":          "michael-2026",
      "title":        "Michael",
      "year":         2026,
      "movie_url":    "/movie/Michael-(2026)",
      "opening_date": "2026-04-24",
      "days": [
        {"date": "2026-04-24", "gross": 12345678, "total_gross": 12345678,
         "theaters": 3955, "rank": 1, "days_in_release": 0},
        ...
      ]
    }

Key strategy mirrors aggregate_movie_weekends.py: norm_title(title) + "-" +
year (year pulled from movie_url's -(YYYY) suffix when present), falling
back to the plain normalized title. Films whose movie_url dropped the year
on a later day still merge correctly via a title→url cache built in pass 1.

Run from the repo root:
    python3 scripts/build_movie_daily_shards.py
"""

import json
import os
import re
import glob
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(REPO_ROOT, "data", "daily")
OUT_DIR   = os.path.join(REPO_ROOT, "data", "movie_daily_shards")


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def year_from_movie_url(url):
    if not url:
        return None
    m = re.search(r"\((\d{4})", url)
    return int(m.group(1)) if m else None


def slug_for(title, movie_url):
    name_key = norm_title(title)
    year = year_from_movie_url(movie_url)
    if year:
        return (f"{name_key}-{year}", year)
    return (name_key, None)


def main():
    files = sorted(
        f for f in glob.glob(os.path.join(DAILY_DIR, "*.json"))
        if not f.endswith("index.json")
    )

    # Pass 1: title -> url cache (some days drop movie_url).
    url_for_title = {}
    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for row in d.get("chart", []):
            t = row.get("title")
            url = (row.get("movie_url") or "").strip()
            if not t or not url:
                continue
            tk = norm_title(t)
            if tk and tk not in url_for_title:
                url_for_title[tk] = url

    # Pass 2: bucket every daily row under its slug-key.
    movies = {}
    total_files = 0
    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        date = d.get("date") or os.path.basename(path).replace(".json", "")
        if not date:
            continue
        total_files += 1
        for row in d.get("chart", []):
            t = row.get("title")
            if not t:
                continue
            url = (row.get("movie_url") or "").strip()
            if not url:
                url = url_for_title.get(norm_title(t), "")
            key, year = slug_for(t, url)
            if not key:
                continue
            bucket = movies.setdefault(key, {
                "title": t, "year": year, "movie_url": url,
                "_latest": "", "rows": [],
            })
            if date > bucket["_latest"]:
                bucket["title"] = t
                bucket["_latest"] = date
                if url:
                    bucket["movie_url"] = url
            bucket["rows"].append({
                "date":            date,
                "gross":           row.get("daily_gross") or 0,
                "total_gross":     row.get("total_gross") or 0,
                "theaters":        row.get("theaters"),
                "rank":            row.get("rank"),
                "days_in_release": row.get("days_in_release"),
                "is_new":          bool(row.get("is_new")),
            })

    os.makedirs(OUT_DIR, exist_ok=True)

    payloads = {}
    titles_index = {}
    plain_to_slugs = {}
    total_days = 0

    for key, b in movies.items():
        rows = sorted(b["rows"], key=lambda r: r["date"])
        seen = set()
        deduped = []
        for r in rows:
            if r["date"] in seen:
                continue
            seen.add(r["date"])
            deduped.append(r)
        if not deduped:
            continue
        payloads[key] = {
            "key":          key,
            "title":        b["title"],
            "year":         b.get("year"),
            "movie_url":    b.get("movie_url") or "",
            "opening_date": deduped[0]["date"],
            "days":         deduped,
        }
        titles_index[key] = b["title"]
        total_days += len(deduped)
        plain = norm_title(b["title"])
        plain_to_slugs.setdefault(plain, []).append((key, b["_latest"]))

    aliases = {}
    for plain, options in plain_to_slugs.items():
        if len(options) == 1 and options[0][0] == plain:
            continue
        winner_slug = sorted(options, key=lambda x: x[1], reverse=True)[0][0]
        aliases[plain] = winner_slug
        if plain not in payloads and winner_slug in payloads:
            payloads[plain] = dict(payloads[winner_slug])

    def shard_letter(s):
        if not s:
            return "_"
        c = s[0].lower()
        return c if "a" <= c <= "z" else "_"

    shards = {}
    for slug, payload in payloads.items():
        shards.setdefault(shard_letter(slug), {})[slug] = payload

    now_iso = datetime.now(timezone.utc).isoformat()
    for letter, entries in shards.items():
        path = os.path.join(OUT_DIR, f"{letter}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "updated": now_iso,
                "letter":  letter,
                "count":   len(entries),
                "entries": entries,
            }, f, ensure_ascii=False)

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated": now_iso,
            "count":   len(titles_index),
            "titles":  titles_index,
            "aliases": aliases,
            "shards":  sorted(shards.keys()),
        }, f, ensure_ascii=False)

    print("Wrote sharded daily archives to " + OUT_DIR)
    print("  daily files read: {:>7,}".format(total_files))
    print("  films (slugged):  {:>7,}".format(len(titles_index)))
    print("  legacy aliases:   {:>7,}".format(len(aliases)))
    print("  shard files:      {:>7,}".format(len(shards) + 1))
    print("  movie-days in:    {:>7,}".format(total_days))


if __name__ == "__main__":
    main()
