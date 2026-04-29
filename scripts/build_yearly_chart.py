#!/usr/bin/env python3
"""
Aggregate per-weekend chart files (data/weekends/{date}.json) into a yearly
chart for the requested year. Output:
    data/yearly.json          (always — current year live chart)
    data/years/{year}.json    (only when --archive is passed; for finalizing
                               a closed year)

Usage:
    python3 scripts/build_yearly_chart.py              # current year → yearly.json
    python3 scripts/build_yearly_chart.py 2026         # explicit year → yearly.json
    python3 scripts/build_yearly_chart.py 2025 --archive   # write data/years/2025.json

Run weekly (recommended: every Monday after weekend actuals are scraped).
"""
import json, os, sys, glob, argparse
from datetime import datetime
from collections import defaultdict


def normalize_title(s):
    """Light normalization to merge title variants across weekends.
    Mostly trims whitespace; we preserve the canonical-cased title from
    the most recent weekend the film appeared in."""
    return (s or "").strip()


def find_release_years():
    """Scan ALL weekend files (every year we have data for) and return a
    dict: normalized_title -> the YEAR of the film's first appearance.

    A film's "first appearance" is read from the earliest weekend file in
    which the title shows up. We treat that year as its release year so
    holdovers crossing the calendar boundary don't get double-counted in
    the wrong year's chart.
    """
    weekends_dir = "data/weekends"
    files = sorted(glob.glob(os.path.join(weekends_dir, "*.json")))
    first_year = {}  # norm_title -> year
    for path in files:
        base = os.path.basename(path).replace(".json", "")
        if not base[:4].isdigit():
            continue
        year = int(base[:4])
        try:
            with open(path) as f:
                wknd = json.load(f)
        except Exception:
            continue
        for row in (wknd.get("chart") or []):
            t = normalize_title(row.get("title"))
            if not t:
                continue
            if t.lower().startswith("reporting:"):
                continue
            key = t.lower()
            if key not in first_year:
                first_year[key] = year
    return first_year


def aggregate_year(year):
    # Build the release-year map once so we can filter holdovers out of
    # the year we're aggregating.
    release_year = find_release_years()

    weekends_dir = "data/weekends"
    pattern = os.path.join(weekends_dir, f"{year}-*.json")
    files = sorted(glob.glob(pattern))

    # title -> aggregated record
    movies = {}
    weekends_seen = 0

    for path in files:
        try:
            with open(path) as f:
                wknd = json.load(f)
        except Exception:
            continue

        chart = wknd.get("chart") or []
        if not chart:
            continue
        weekends_seen += 1

        date_from = wknd.get("date_from") or ""

        for row in chart:
            title = normalize_title(row.get("title"))
            if not title:
                continue
            # Skip scraper footer rows ("Reporting: 71" etc.) that older
            # scraper builds accidentally captured as chart entries.
            if title.lower().startswith("reporting:"):
                continue
            # Holdover filter: only include films whose first appearance
            # in our weekend data was in this year. Avatar: Fire and Ash
            # (released Dec 2024) won't show up in the 2026 chart even
            # though it had revenue here.
            if release_year.get(title.lower()) != year:
                continue

            wknd_gross = row.get("weekend_gross") or 0
            theaters   = row.get("theaters") or 0
            distrib    = row.get("distributor") or ""
            is_new     = bool(row.get("is_new"))
            wkn_rank   = row.get("rank") or 0
            wknd_total = row.get("total_gross") or 0  # film cumulative as of this weekend

            m = movies.get(title)
            if m is None:
                m = movies[title] = {
                    "title":            title,
                    "distributor":      distrib,
                    "total_gross":      0,
                    "max_theaters":     0,
                    "opening_weekend":  None,
                    "opening_theaters": None,
                    "open_date":        None,
                    "weekends_in_chart": 0,
                    "best_rank":         9999,
                    "_latest_total":     0,
                }

            # Always update distributor when we see a non-empty value.
            if distrib and not m["distributor"]:
                m["distributor"] = distrib

            m["total_gross"]       += wknd_gross
            m["max_theaters"]       = max(m["max_theaters"], theaters or 0)
            m["weekends_in_chart"] += 1
            m["best_rank"]          = min(m["best_rank"], wkn_rank or 9999)
            m["_latest_total"]      = max(m["_latest_total"], wknd_total)

            # Opening weekend = the first weekend we see this film as new
            # (or, failing an is_new flag, the earliest weekend recorded).
            if m["opening_weekend"] is None or (is_new and m["open_date"] is None):
                m["opening_weekend"]  = wknd_gross
                m["opening_theaters"] = theaters
                # Format "Apr 17" from date_from
                try:
                    dt = datetime.strptime(date_from, "%Y-%m-%d")
                    m["open_date"] = dt.strftime("%b %-d")
                except Exception:
                    m["open_date"] = date_from[5:] if date_from else None

    # Prefer the cumulative total from the latest weekend if it's larger
    # than our running sum (the running sum only counts weekends, while
    # total_gross from each weekend file already includes weekday gross).
    for m in movies.values():
        if m["_latest_total"] and m["_latest_total"] > m["total_gross"]:
            m["total_gross"] = m["_latest_total"]
        del m["_latest_total"]

    # Rank by total_gross descending
    rows = sorted(movies.values(), key=lambda m: -m["total_gross"])
    for i, m in enumerate(rows, start=1):
        m["rank"] = i

    return rows, weekends_seen


def write_output(year, rows, target_path):
    payload = {
        "year":    year,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "source":  "weekend-aggregate",
        "chart":   rows,
    }
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "w") as f:
        json.dump(payload, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", nargs="?", type=int, default=datetime.now().year)
    ap.add_argument("--archive", action="store_true",
                    help="Also write data/years/{year}.json (use to freeze a closed year)")
    args = ap.parse_args()

    rows, weekends = aggregate_year(args.year)
    print(f"Aggregated {len(rows)} films across {weekends} weekend files for {args.year}")

    # Always update yearly.json (current-year live)
    yearly_path = "data/yearly.json"
    write_output(args.year, rows, yearly_path)
    print(f"Wrote {yearly_path}")

    if args.archive:
        archive_path = f"data/years/{args.year}.json"
        write_output(args.year, rows, archive_path)
        print(f"Wrote {archive_path}")

    # Show top 5 for sanity
    if rows:
        print("\nTop 5:")
        for m in rows[:5]:
            print(f"  {m['rank']}. {m['title']:<40} ${m['total_gross']:>13,}")


if __name__ == "__main__":
    main()
