"""
Box Office Jedi — Aggregate Weekend Grosses per Movie
=====================================================
Reads every file in data/weekends/*.json and produces one compact JSON
per movie under data/movie_weekends/, plus a lightweight index.

    data/movie_weekends/index.json          — { keys: {key:title,...},
                                                aliases: {plain_key:slug_key} }
    data/movie_weekends/<slug>.json         — per-movie weekend data

Per-movie file shape:
    {
      "key":           "michael-2026",      # slug-form, year-disambiguated
      "title":         "Michael",
      "year":          2026,
      "movie_url":     "/movie/Michael-(2026)",
      "opening_date":  "2026-04-24",
      "opening_gross": 97206874,
      "weekends": [...]
    }

Key strategy
------------
Two films can share a normalized title (e.g., "Michael" 1996 and
"Michael" 2026). To keep their data SEPARATE, we key by:

    slug = norm_title(name) + "-" + year

derived from the scraped `movie_url` (which encodes the year, like
`/movie/Michael-(2026)`). When `movie_url` is missing we fall back to
the plain norm_title key.

For backward compatibility with old `movie.html?title=` links, we also
write an `aliases` index entry mapping the plain title key to the
canonical slug — which is the slug whose data is the most recent
(latest opening date). Old links resolve to whichever Michael is
currently most relevant; specific links can pass `?slug=michael-2026`.

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


def year_from_movie_url(url: str) -> int | None:
    """Extract the release year from a /movie/Title-(YYYY) style url."""
    if not url:
        return None
    m = re.search(r"\((\d{4})", url)
    return int(m.group(1)) if m else None


def slug_for(title: str, movie_url: str | None) -> tuple[str, int | None]:
    """Build a key for this row. Returns (key, year).
    If movie_url has a year, key = norm_title-year. Otherwise key = norm_title.
    """
    name_key = norm_title(title)
    year = year_from_movie_url(movie_url)
    if year:
        return (f"{name_key}-{year}", year)
    return (name_key, None)


def main():
    files = sorted(f for f in glob.glob(os.path.join(WEEKENDS, "*.json"))
                   if not f.endswith("index.json"))

    # ── Pass 1: build a title→url cache so rows that lost movie_url between
    # weeks still get keyed correctly. ──────────────────────────────────────
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

    # ── Pass 2: bucket every weekend row under its slug-key ────────────────
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
            url = (row.get("movie_url") or "").strip()
            if not url:
                url = url_for_title.get(norm_title(t), "")
            key, year = slug_for(t, url)
            if not key:
                continue
            bucket = movies.setdefault(key, {
                "title":      t,
                "year":       year,
                "movie_url":  url,
                "_latest":    "",
                "rows":       [],
            })
            if date_from > bucket["_latest"]:
                bucket["title"]   = t                # canonicalize on most recent appearance
                bucket["_latest"] = date_from
                if url:
                    bucket["movie_url"] = url
            bucket["rows"].append({
                "date":        date_from,
                "gross":       row.get("weekend_gross") or 0,
                "rank":        row.get("rank"),
                "theaters":    row.get("theaters"),
                "total_gross": row.get("total_gross"),
            })

    os.makedirs(OUT_DIR, exist_ok=True)

    # ── Write per-movie files ──────────────────────────────────────────────
    titles_index = {}        # slug → title
    plain_to_slugs = {}      # plain_key → list of (slug, latest_date) — used to
                             # decide which slug owns the plain-key alias

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
            "year":          b.get("year"),
            "movie_url":     b.get("movie_url") or "",
            "opening_date":  weekends[0]["date"],
            "opening_gross": weekends[0]["gross"],
            "weekends":      weekends,
        }
        with open(os.path.join(OUT_DIR, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(movie, f, indent=1, ensure_ascii=False)
        titles_index[key] = b["title"]
        total_weekends += len(weekends)

        # Track plain-key aliases for backward compat
        plain = norm_title(b["title"])
        plain_to_slugs.setdefault(plain, []).append((key, b["_latest"]))

    # ── For each plain title, pick the slug whose latest weekend is most
    # recent and write that as `{plain}.json` too — keeps old movie.html
    # ?title= links working. ─────────────────────────────────────────────
    aliases = {}
    for plain, options in plain_to_slugs.items():
        # If there's only one slug for this title, the file is already named
        # plain (since slug == plain when there's no year). No alias needed.
        if len(options) == 1 and options[0][0] == plain:
            continue
        winner_slug = sorted(options, key=lambda x: x[1], reverse=True)[0][0]
        aliases[plain] = winner_slug
        # Write a copy of the winner's data as plain.json so legacy links work.
        src = os.path.join(OUT_DIR, winner_slug + ".json")
        dst = os.path.join(OUT_DIR, plain + ".json")
        if os.path.exists(src) and src != dst:
            with open(src, encoding="utf-8") as f:
                data = json.load(f)
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)

    # Index file: lists every key (slug) and the plain-title aliases
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated":  datetime.utcnow().isoformat(),
            "count":    len(titles_index),
            "titles":   titles_index,
            "aliases":  aliases,
        }, f, indent=1, ensure_ascii=False)

    print("Wrote per-movie files to " + OUT_DIR)
    print("  films (slugged):  {:>7,}".format(len(titles_index)))
    print("  legacy aliases:   {:>7,}".format(len(aliases)))
    print("  weekends in:      {:>7,}".format(total_weekends))


if __name__ == "__main__":
    main()
