"""
Box Office Jedi — The Numbers Scraper
======================================
Scrapes daily and weekend box office data from The Numbers (the-numbers.com)
and outputs clean JSON files for the website to consume.

Run manually:   python3 scrape_the_numbers.py
Run via GitHub Actions: automated daily at 9am ET (see .github/workflows/update-data.yml)

Output files:
  data/daily.json    — today's daily chart
  data/weekend.json  — most recent weekend chart
  data/yearly.json   — year-to-date chart
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
import time

# ── Configuration ─────────────────────────────────────────────────────────────

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

BASE_URL = "https://www.the-numbers.com"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> BeautifulSoup | None:
    """Fetch a URL with retries and polite rate limiting."""
    for attempt in range(retries):
        try:
            time.sleep(1.5)  # Be polite — don't hammer the server
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "lxml")
            elif resp.status_code == 429:
                print(f"  Rate limited. Waiting 30s before retry {attempt+1}...")
                time.sleep(30)
            else:
                print(f"  HTTP {resp.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(5)
    return None


def parse_money(s: str) -> int:
    """Convert '$12,345,678' or '$12.3M' to an integer."""
    if not s:
        return 0
    s = s.strip().replace("$", "").replace(",", "").replace(" ", "")
    if s.endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    try:
        return int(s)
    except ValueError:
        return 0


def save_json(filename: str, data: dict | list):
    """Save data as formatted JSON to the data/ directory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")


# ── Daily Chart ───────────────────────────────────────────────────────────────

def scrape_daily(date: datetime = None) -> list[dict]:
    """
    Scrape The Numbers daily box office chart for a given date.
    Defaults to yesterday (since today's data posts overnight).
    """
    if date is None:
        date = datetime.now() - timedelta(days=1)

    date_str = date.strftime("%Y/%m/%d")
    url = f"{BASE_URL}/box-office-chart/daily/{date_str}"
    print(f"\n[Daily] Fetching: {url}")

    soup = fetch(url)
    if not soup:
        print("  Failed to fetch daily chart.")
        return []

    # The Numbers uses a <table id="box_office_daily"> or similar
    # We look for the main data table with box office rows
    table = soup.find("table", id=lambda x: x and "box_office" in x.lower())
    if not table:
        # Fallback: find any table with rank/gross columns
        tables = soup.find_all("table")
        table = tables[1] if len(tables) > 1 else None

    if not table:
        print("  Could not find data table.")
        return []

    rows = table.find_all("tr")[1:]  # Skip header row
    results = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        try:
            entry = {
                "rank":          int(cells[0].get_text(strip=True).replace("#", "") or 0),
                "title":         cells[1].get_text(strip=True),
                "movie_url":     cells[1].find("a")["href"] if cells[1].find("a") else "",
                "distributor":   cells[2].get_text(strip=True) if len(cells) > 2 else "",
                "daily_gross":   parse_money(cells[3].get_text(strip=True)),
                "theaters":      int(cells[4].get_text(strip=True).replace(",", "") or 0) if len(cells) > 4 else 0,
                "avg_per_theater": parse_money(cells[5].get_text(strip=True)) if len(cells) > 5 else 0,
                "total_gross":   parse_money(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
                "days_in_release": int(cells[7].get_text(strip=True) or 0) if len(cells) > 7 else 0,
            }
            if entry["title"] and entry["daily_gross"] > 0:
                results.append(entry)
        except (ValueError, TypeError, KeyError):
            continue

    print(f"  Found {len(results)} entries.")
    return results


# ── Weekend Chart ─────────────────────────────────────────────────────────────

def scrape_weekend(date: datetime = None) -> list[dict]:
    """
    Scrape The Numbers weekend box office chart.
    Date should be the Friday of the target weekend.
    Defaults to most recent completed weekend.
    """
    if date is None:
        # Find the most recent Friday
        today = datetime.now()
        days_since_friday = (today.weekday() - 4) % 7
        date = today - timedelta(days=days_since_friday)
        # If it's before Monday morning (data not posted yet), go back another week
        if today.weekday() < 1:
            date -= timedelta(days=7)

    date_str = date.strftime("%Y/%m/%d")
    url = f"{BASE_URL}/box-office-chart/weekend/{date_str}"
    print(f"\n[Weekend] Fetching: {url}")

    soup = fetch(url)
    if not soup:
        print("  Failed to fetch weekend chart.")
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
        if len(cells) < 5:
            continue
        try:
            # Parse % change (e.g. "-42%" or "NEW")
            change_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
            if change_text.upper() == "NEW":
                change_pct = None  # New release
            else:
                try:
                    change_pct = float(change_text.replace("%", "").replace("+", ""))
                except ValueError:
                    change_pct = None

            entry = {
                "rank":            int(cells[0].get_text(strip=True).replace("#", "") or 0),
                "title":           cells[1].get_text(strip=True),
                "movie_url":       cells[1].find("a")["href"] if cells[1].find("a") else "",
                "distributor":     cells[2].get_text(strip=True) if len(cells) > 2 else "",
                "weekend_gross":   parse_money(cells[3].get_text(strip=True)),
                "change_pct":      change_pct,
                "is_new":          change_text.upper() == "NEW",
                "theaters":        int(cells[5].get_text(strip=True).replace(",", "") or 0) if len(cells) > 5 else 0,
                "avg_per_theater": parse_money(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
                "total_gross":     parse_money(cells[7].get_text(strip=True)) if len(cells) > 7 else 0,
                "weeks_in_release": int(cells[8].get_text(strip=True) or 0) if len(cells) > 8 else 0,
            }
            if entry["title"] and entry["weekend_gross"] > 0:
                results.append(entry)
        except (ValueError, TypeError, KeyError):
            continue

    print(f"  Found {len(results)} entries.")
    return results


# ── Yearly Chart ──────────────────────────────────────────────────────────────

def scrape_yearly(year: int = None) -> list[dict]:
    """Scrape The Numbers year-to-date domestic chart."""
    if year is None:
        year = datetime.now().year

    url = f"{BASE_URL}/box-office-chart/year/{year}"
    print(f"\n[Yearly] Fetching: {url}")

    soup = fetch(url)
    if not soup:
        print("  Failed to fetch yearly chart.")
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
            entry = {
                "rank":          int(cells[0].get_text(strip=True).replace("#", "") or 0),
                "title":         cells[1].get_text(strip=True),
                "movie_url":     cells[1].find("a")["href"] if cells[1].find("a") else "",
                "distributor":   cells[2].get_text(strip=True) if len(cells) > 2 else "",
                "total_gross":   parse_money(cells[3].get_text(strip=True)),
            }
            if entry["title"] and entry["total_gross"] > 0:
                results.append(entry)
        except (ValueError, TypeError, KeyError):
            continue

    print(f"  Found {len(results)} entries.")
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now()
    print(f"Box Office Jedi Scraper — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Daily chart (yesterday's data)
    daily = scrape_daily()
    save_json("daily.json", {
        "updated": now.isoformat(),
        "date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "chart": daily
    })

    # Weekend chart (most recent completed weekend)
    weekend = scrape_weekend()
    save_json("weekend.json", {
        "updated": now.isoformat(),
        "chart": weekend
    })

    # Yearly chart (current year)
    yearly = scrape_yearly()
    save_json("yearly.json", {
        "updated": now.isoformat(),
        "year": now.year,
        "chart": yearly
    })

    print("\n" + "=" * 60)
    print("Done! JSON files written to data/")
    print("  data/daily.json")
    print("  data/weekend.json")
    print("  data/yearly.json")


if __name__ == "__main__":
    main()
