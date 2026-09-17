#!/usr/bin/env python3
"""
Build the All-Time Domestic Grosses chart (data/charts/domestic-lifetime.json)
from data/movie_weekends_shards/*.json — the per-movie weekend-history shards
that are already rebuilt on every scrape by aggregate_movie_weekends.py.

This replaces the old alltime-domestic.html, which had its entire top-200
chart hardcoded as a static JS array and never updated after it was written.
The new file follows the same {slug, label, category, source, updated,
columns, rows} schema every other data/charts/*.json file uses, so it renders
through the generic alltime-chart.html?chart=domestic-lifetime viewer and
gets picked up automatically by build_movie_charts_index.py (movie profile
"Charts" panel) just like every other all-time chart.

A film's lifetime domestic gross is the maximum `total_gross` seen across its
weekend history (cumulative-to-date, so the last/highest entry is the
lifetime figure — same approach build_yearly_chart.py uses for the current
year).

Known limitation: this inherits data/movie_weekends_shards' existing title-
collision issue (CLAUDE.md "Known bugs" #2) — a shard keyed by bare title
(no -(YYYY) suffix in movie_url) can blend weekends from a same-titled
original and its reissue/remake. This script filters obvious reissues by
title keyword (see REISSUE_TITLE_PHRASES) but does not attempt the deeper
per-URL shard split described in that known-bugs entry.

Usage:
    python3 scripts/build_alltime_chart.py
"""
import json
import glob
import os
from datetime import datetime

SHARDS_DIR = "data/movie_weekends_shards"
OUT_PATH = "data/charts/domestic-lifetime.json"
INDEX_PATH = "data/charts/index.json"
TOP_N = 200

REISSUE_TITLE_PHRASES = (
    "re-release", "rerelease", "re release",
    "reissue",
    "restoration", "4k restoration", "restored",
    "anniversary",
    "imax re-release",
    "(re-release)",
    "remastered",
)


def is_reissue_title(title):
    if not title:
        return False
    low = title.lower()
    return any(p in low for p in REISSUE_TITLE_PHRASES)


def fmt_dollars(n):
    return "$" + "{:,}".format(int(n))


def main():
    shard_paths = sorted(glob.glob(os.path.join(SHARDS_DIR, "*.json")))
    if not shard_paths:
        print(f"No shard files found in {SHARDS_DIR} — aborting.")
        return

    films = []
    for path in shard_paths:
        try:
            with open(path) as f:
                shard = json.load(f)
        except Exception as e:
            print(f"  skip {path}: {e}")
            continue
        entries = shard.get("entries") or {}
        for key, rec in entries.items():
            title = (rec.get("title") or "").strip()
            if not title or is_reissue_title(title):
                continue
            weekends = rec.get("weekends") or []
            if not weekends:
                continue
            lifetime = max((w.get("total_gross") or 0) for w in weekends)
            if lifetime <= 0:
                continue
            films.append({
                "title": title,
                "year": rec.get("year"),
                "lifetime": lifetime,
            })

    # De-dupe by (title, year) in case a film's key appears in more than one
    # shard due to a title starting-letter mismatch; keep the higher figure.
    best = {}
    for m in films:
        dk = (m["title"], m["year"])
        if dk not in best or m["lifetime"] > best[dk]["lifetime"]:
            best[dk] = m

    ranked = sorted(best.values(), key=lambda m: -m["lifetime"])[:TOP_N]

    columns = ["Rank", "Title", "Lifetime Gross", "Year"]
    rows = []
    for i, m in enumerate(ranked, start=1):
        rows.append([
            str(i),
            m["title"],
            fmt_dollars(m["lifetime"]),
            str(m["year"]) if m["year"] else "",
        ])

    payload = {
        "slug": "domestic-lifetime",
        "label": "All-Time Domestic Grosses",
        "category": "Grosses",
        "source": "movie-weekends-shards-aggregate",
        "updated": datetime.now().isoformat(timespec="seconds"),
        "columns": columns,
        "rows": rows,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_PATH} ({len(rows)} rows)")
    if rows:
        print("Top 5:")
        for r in rows[:5]:
            print(" ", r)

    # Keep data/charts/index.json's entry for this chart in sync.
    try:
        with open(INDEX_PATH) as f:
            idx = json.load(f)
    except Exception:
        idx = {"updated": "", "charts": []}

    entry = {
        "slug": "domestic-lifetime",
        "label": "All-Time Domestic Grosses",
        "category": "Grosses",
        "href": "alltime-chart.html?chart=domestic-lifetime",
        "updated": datetime.now().strftime("%b %d, %Y"),
        "rows": len(rows),
    }
    charts = idx.get("charts") or []
    replaced = False
    for i, c in enumerate(charts):
        if c.get("slug") == "domestic-lifetime":
            charts[i] = entry
            replaced = True
            break
    if not replaced:
        charts.insert(0, entry)
    idx["charts"] = charts
    idx["updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(INDEX_PATH, "w") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)
    print(f"Updated {INDEX_PATH}")


if __name__ == "__main__":
    main()
