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
import json, os, sys, glob, re, argparse
from datetime import datetime
from collections import defaultdict


# The Numbers gives reissues their own page with the original release year
# in parens, e.g. /movie/Top-Gun-(1986) or /movie/Shrek-(2001). The original
# page is the bare slug (/movie/Top-Gun, /movie/Shrek). When that paren-year
# is OLDER than the year we're aggregating, it's a reissue and shouldn't
# pollute the year's chart.
_REISSUE_URL_YEAR_RE = re.compile(r"-\((\d{4})\)/?$")


def is_reissue_by_url(movie_url: str, chart_year: int) -> bool:
    if not movie_url:
        return False
    m = _REISSUE_URL_YEAR_RE.search(movie_url.rstrip("/"))
    if not m:
        return False
    return int(m.group(1)) < chart_year


# Title-keyword phrases that almost always mark a reissue / restoration /
# anniversary screening — even when The Numbers' URL uses the chart year.
# Case-insensitive substring match. Order doesn't matter.
_REISSUE_TITLE_PHRASES = (
    "re-release", "rerelease", "re release",
    "reissue",
    "restoration", "4k restoration", "restored",
    "anniversary",
    "imax re-release",
    "(re-release)",
    "remastered",
)


def is_reissue_by_title(title: str) -> bool:
    if not title:
        return False
    low = title.lower()
    return any(p in low for p in _REISSUE_TITLE_PHRASES)


def is_stealth_reissue(record: dict) -> bool:
    """Catches reissues whose URL DOESN'T encode the original year — e.g.
    TMNT II, where The Numbers reuses the original page for the reissue.
    Signal: the source's lifetime cumulative gross dwarfs what the film
    actually took in this calendar year, AND the film only played in a
    limited footprint. A genuine current-year release would have lifetime
    ≈ 1.1-1.3× yearly sum (lifetime adds weekdays); a reissue's lifetime
    carries the original run, so the ratio explodes."""
    lifetime = record.get("_latest_total") or 0
    yearly   = record.get("_running_sum") or 0
    theaters = record.get("max_theaters") or 0
    if yearly <= 0 or lifetime <= 0:
        return False
    if theaters >= 2000:
        return False
    return lifetime > yearly * 5


def normalize_title(s):
    """Light normalization to merge title variants across weekends.
    Mostly trims whitespace; we preserve the canonical-cased title from
    the most recent weekend the film appeared in."""
    return (s or "").strip()


def display_title(s):
    """Strip wrapping curly/straight quotes from a title before display.
    The scraper occasionally captures titles wrapped in “smart quotes”
    (e.g. "“Wuthering Heights”") — those don't belong in the chart."""
    s = (s or "").strip()
    return s.strip('“”"\'')


def film_key(row, url_for_title=None):
    """Unique key for a film, used to merge weekend rows of the same
    film. Prefers movie_url (which encodes the release year, so
    Michael-(2026) is distinct from Michael-(1996)); falls back to
    a cached URL looked up by title when this row's movie_url is
    missing (the scraper occasionally drops it on follow-up weekends);
    finally falls back to title when no URL has ever been seen."""
    url = (row.get("movie_url") or "").strip()
    if url:
        return ("url", url)
    t = normalize_title(row.get("title")).lower()
    if url_for_title and t in url_for_title:
        return ("url", url_for_title[t])
    return ("title", t)


def find_release_years():
    """Scan ALL weekend files and return:
       (first_year, url_for_title)

    first_year:    film_key -> YEAR of first appearance
    url_for_title: lower(title) -> first non-empty movie_url ever seen.
                   Used to merge later weekends where the scraper dropped
                   the movie_url field but the title is still recognizable.
    """
    weekends_dir = "data/weekends"
    files = sorted(glob.glob(os.path.join(weekends_dir, "*.json")))

    # First sub-pass: build title->url cache so subsequent keying is stable.
    url_for_title = {}
    for path in files:
        try:
            with open(path) as f:
                wknd = json.load(f)
        except Exception:
            continue
        for row in (wknd.get("chart") or []):
            t = normalize_title(row.get("title"))
            url = (row.get("movie_url") or "").strip()
            if not t or not url:
                continue
            tl = t.lower()
            if tl not in url_for_title:
                url_for_title[tl] = url

    # Second sub-pass: build first_year using the resolved keys.
    first_year = {}
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
            key = film_key(row, url_for_title)
            if key not in first_year:
                first_year[key] = year
    return first_year, url_for_title


def aggregate_year(year):
    # Build the release-year map + title->url cache once so we can
    # (a) filter holdovers out of the year we're aggregating, and
    # (b) merge weekends of the same film even if the scraper drops
    # movie_url between weeks.
    release_year, url_for_title = find_release_years()

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
            # in our weekend data was in this year. Same-titled remakes
            # (e.g. Michael 1996 vs Michael 2026) are distinguished via
            # movie_url so the 2026 film classifies as a 2026 release.
            key = film_key(row, url_for_title)
            if release_year.get(key) != year:
                continue

            # Reissue filter (primary): The Numbers labels reissues with
            # the original year in parens. /movie/Shrek-(2001) showing up
            # in 2026 is a re-release, not a 2026 movie.
            row_url = (row.get("movie_url") or "").strip()
            if is_reissue_by_url(row_url, year):
                continue
            # Title-keyword filter: catches explicit re-releases the URL
            # missed, e.g. "Hamilton 2025 Re-release", "Princess Mononoke
            # 4K Restoration", "Pride & Prejudice 20th Anniversary".
            if is_reissue_by_title(title):
                continue

            wknd_gross = row.get("weekend_gross") or 0
            theaters   = row.get("theaters") or 0
            distrib    = row.get("distributor") or ""
            is_new     = bool(row.get("is_new"))
            wkn_rank   = row.get("rank") or 0
            wknd_total = row.get("total_gross") or 0  # film cumulative as of this weekend

            m = movies.get(key)
            if m is None:
                m = movies[key] = {
                    "title":            display_title(title),
                    "distributor":      distrib,
                    "total_gross":      0,
                    "max_theaters":     0,
                    "opening_weekend":  None,
                    "opening_theaters": None,
                    "open_date":        None,
                    "weekends_in_chart": 0,
                    "best_rank":         9999,
                    "_latest_total":     0,
                    "_running_sum":      0,
                }

            # Always update distributor when we see a non-empty value.
            if distrib and not m["distributor"]:
                m["distributor"] = distrib

            m["total_gross"]       += wknd_gross
            m["_running_sum"]      += wknd_gross  # year-only sum, for stealth-reissue test
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

    # Reissue filter (secondary, stealth): drop films where the source's
    # lifetime gross dwarfs what they actually took this year on a small
    # footprint — catches reissues that share the original page's URL
    # (no -(YYYY) suffix), like TMNT II: The Secret of the Ooze.
    stealth_filtered = [k for k, m in movies.items() if is_stealth_reissue(m)]
    for k in stealth_filtered:
        del movies[k]

    # Prefer the cumulative total from the latest weekend ONLY when it's
    # within reasonable range of our yearly sum (lifetime should be ≈ 1.1-
    # 1.3× weekend sum once weekdays are folded in). If lifetime is way
    # bigger than the yearly sum, that's a reissue's pre-existing total
    # leaking in — fall back to the year-only sum.
    for m in movies.values():
        latest = m["_latest_total"]
        yearly = m["_running_sum"]
        if latest and yearly and latest <= yearly * 3:
            # Trustworthy lifetime — use it (it includes weekday grosses).
            m["total_gross"] = max(latest, yearly)
        else:
            # Either no lifetime data or it dwarfs the yearly sum.
            m["total_gross"] = yearly
        del m["_latest_total"]
        del m["_running_sum"]

    # Rank by total_gross descending
    rows = sorted(movies.values(), key=lambda m: -m["total_gross"])
    for i, m in enumerate(rows, start=1):
        m["rank"] = i

    return rows, weekends_seen, stealth_filtered


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

    rows, weekends, stealth_filtered = aggregate_year(args.year)
    print(f"Aggregated {len(rows)} films across {weekends} weekend files for {args.year}")
    if stealth_filtered:
        print(f"  Filtered {len(stealth_filtered)} stealth reissues (lifetime gross >> yearly take)")

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
