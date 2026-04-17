"""
Box Office Jedi — Historical Weekend Backfill Scraper
======================================================
One-time script to scrape all past weekend box office charts from
The Numbers and populate:
  data/weekends/YYYY-MM-DD.json   — full chart for each weekend
  data/weekends.json              — master index (for weekend.html)

Run once from the repo root:
  python3 scripts/scrape_historical.py

Optional arguments:
  --start YYYY-MM-DD   First Friday to scrape  (default: 1995-01-06)
  --end   YYYY-MM-DD   Last Friday to scrape   (default: most recent completed weekend)
  --skip-existing      Skip dates that already have a data/weekends/YYYY-MM-DD.json file

The script is polite — it waits 2 seconds between requests and backs off on 429s.
A full 1995→present run (~1,600 weekends) takes several hours. Older weekends
(especially pre-2000) may return empty or partial charts; the script skips
those and continues.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import argparse
from datetime import datetime, timedelta, date

# ── Configuration ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.the-numbers.com/",
}

BASE_URL  = "https://www.the-numbers.com"
DATA_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
WKNDS_DIR = os.path.join(DATA_DIR, "weekends")

# ── Helpers ────────────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 4) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            time.sleep(2.0)
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "lxml")
            elif resp.status_code == 404:
                print(f"  404 — no data for this date, skipping.")
                return None
            elif resp.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {resp.status_code} — retry {attempt+1}")
                time.sleep(5)
        except requests.RequestException as e:
            print(f"  Request error: {e} — retry {attempt+1}")
            time.sleep(5)
    return None


def parse_money(s: str) -> int:
    if not s:
        return 0
    s = s.strip().replace("$", "").replace(",", "").replace(" ", "")
    if s.endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    try:
        return int(s)
    except ValueError:
        return 0


def safe_int(s: str) -> int:
    try:
        return int(str(s).replace(",", "").replace("#", "").strip() or 0)
    except (ValueError, AttributeError):
        return 0


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── All Fridays generator ──────────────────────────────────────────────────────

def all_fridays(start: date, end: date):
    """Yield every Friday between start and end (inclusive)."""
    # Advance start to nearest Friday
    d = start
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    while d <= end:
        yield d
        d += timedelta(days=7)


# ── Scrape one weekend ─────────────────────────────────────────────────────────

def scrape_weekend_date(friday: date) -> list[dict]:
    url = f"{BASE_URL}/box-office-chart/weekend/{friday.strftime('%Y/%m/%d')}"
    print(f"  GET {url}")

    soup = fetch(url)
    if not soup:
        return []

    table = soup.find("table", id=lambda x: x and "box_office" in x.lower())
    if not table:
        tables = soup.find_all("table")
        table = tables[1] if len(tables) > 1 else None
    if not table:
        print("  Could not find data table.")
        return []

    rows = table.find_all("tr")[1:]
    results = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            change_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
            is_new = change_text in ("", "-", "n/a") or change_text.upper() == "NEW"
            try:
                change_pct = None if is_new else float(
                    change_text.replace("%", "").replace("+", ""))
            except ValueError:
                change_pct = None

            theaters = safe_int(cells[3].get_text(strip=True))
            gross    = parse_money(cells[2].get_text(strip=True))
            avg      = round(gross / theaters) if theaters > 0 else 0

            entry = {
                "rank":             safe_int(cells[0].get_text(strip=True)),
                "title":            cells[1].get_text(strip=True),
                "movie_url":        cells[1].find("a")["href"] if cells[1].find("a") else "",
                "distributor":      "",
                "weekend_gross":    gross,
                "theaters":         theaters,
                "change_pct":       change_pct,
                "is_new":           is_new,
                "avg_per_theater":  avg,
                "total_gross":      parse_money(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
                "weeks_in_release": safe_int(cells[7].get_text(strip=True)) if len(cells) > 7 else 0,
                "last_rank":        None,
                "theater_change":   None,
            }
            if entry["title"] and entry["weekend_gross"] > 0:
                results.append(entry)
        except (ValueError, TypeError, KeyError):
            continue

    return results


# ── Build / update the master index ───────────────────────────────────────────

def rebuild_index():
    """
    Walk all data/weekends/YYYY-MM-DD.json files and build weekends.json index.
    """
    print("\nRebuilding weekends.json index...")
    weekends = []

    for fname in sorted(os.listdir(WKNDS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(WKNDS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            chart    = d.get("chart", [])
            top10    = chart[:10]
            top_total = sum(m.get("weekend_gross", 0) for m in top10)
            top_film  = chart[0]["title"] if chart else "—"
            weekends.append({
                "date_from":    d.get("date_from", fname.replace(".json", "")),
                "date_to":      d.get("date_to", ""),
                "week_number":  d.get("week_number", 0),
                "top_film":     top_film,
                "top_total":    top_total,
                "change_pct":   None,   # will fill below
                "is_estimates": d.get("is_estimates", False),
            })
        except Exception as e:
            print(f"  Skipping {fname}: {e}")

    # Sort ascending by date so we can compute week-over-week change
    weekends.sort(key=lambda w: w["date_from"])

    for i, w in enumerate(weekends):
        if i > 0:
            prev_total = weekends[i - 1].get("top_total") or 0
            if prev_total > 0 and w["top_total"]:
                w["change_pct"] = round(
                    (w["top_total"] - prev_total) / prev_total * 100, 1)

    # Reverse for descending display
    weekends.sort(key=lambda w: w["date_from"], reverse=True)

    index_path = os.path.join(DATA_DIR, "weekends.json")
    save_json(index_path, {
        "updated":  datetime.now().isoformat(),
        "weekends": weekends,
    })
    print(f"  ✓ weekends.json — {len(weekends)} weekends indexed")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Historical weekend backfill scraper")
    parser.add_argument("--start", default="1995-01-06",
                        help="Start date (Friday) YYYY-MM-DD, default 1995-01-06")
    parser.add_argument("--end",   default=None,
                        help="End date (Friday) YYYY-MM-DD, default = most recent completed")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip dates that already have a JSON file")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)

    if args.end:
        end_date = date.fromisoformat(args.end)
    else:
        # Most recent completed Friday (before current week's data is finalized)
        today = date.today()
        days_since_friday = (today.weekday() - 4) % 7
        last_friday = today - timedelta(days=days_since_friday)
        # If it's before Monday, go back one more week
        if today.weekday() < 1:
            last_friday -= timedelta(days=7)
        end_date = last_friday

    os.makedirs(WKNDS_DIR, exist_ok=True)

    fridays = list(all_fridays(start_date, end_date))
    total = len(fridays)
    print(f"Box Office Jedi — Historical Backfill")
    print(f"Scraping {total} weekends from {start_date} to {end_date}")
    print("=" * 60)

    done = 0
    skipped = 0
    empty = 0

    for i, friday in enumerate(fridays):
        date_str = str(friday)
        out_path = os.path.join(WKNDS_DIR, f"{date_str}.json")

        # Skip if file already exists and flag set
        if args.skip_existing and os.path.exists(out_path):
            skipped += 1
            continue

        print(f"\n[{i+1}/{total}] {date_str}")
        chart = scrape_weekend_date(friday)

        if not chart:
            print(f"  No data — skipping.")
            empty += 1
            continue

        sunday = friday + timedelta(days=2)
        week_num = int(friday.strftime("%U"))

        payload = {
            "updated":     datetime.now().isoformat(),
            "date_from":   date_str,
            "date_to":     str(sunday),
            "week_number": week_num,
            "chart":       chart,
        }
        save_json(out_path, payload)
        done += 1

        # Progress report every 50 weekends
        if (i + 1) % 50 == 0:
            print(f"\n--- Progress: {i+1}/{total} weekends processed ---\n")

    print("\n" + "=" * 60)
    print(f"Done. Scraped: {done} | Skipped: {skipped} | Empty: {empty}")

    # Rebuild the master index from all saved files
    rebuild_index()


if __name__ == "__main__":
    main()
