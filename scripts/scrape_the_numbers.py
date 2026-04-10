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
    path = os.path.join(DATA_DIR, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")


def update_weekends_index(date_from: str, date_to: str, week_number: int,
                          chart: list[dict], is_estimates: bool = False):
    """
    Append or update the weekends.json master index with a summary of this weekend.
    The index powers the weekend.html year-view page.
    """
    index_path = os.path.join(DATA_DIR, "weekends.json")

    # Load existing index
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        weekends = idx.get("weekends", [])
    except (FileNotFoundError, json.JSONDecodeError):
        weekends = []

    # Remove any existing entry for this date (we'll replace it)
    weekends = [w for w in weekends if w.get("date_from") != date_from]

    # Build summary entry
    top10 = chart[:10]
    top_total = sum(m.get("weekend_gross", 0) for m in top10)
    top_film  = chart[0]["title"] if chart else "—"

    # Change vs previous entry in index (if any)
    prev_entries = [w for w in weekends if w.get("date_from") < date_from]
    prev_total   = prev_entries[-1].get("top_total") if prev_entries else None
    change_pct   = None
    if prev_total and prev_total > 0:
        change_pct = round((top_total - prev_total) / prev_total * 100, 1)

    summary = {
        "date_from":    date_from,
        "date_to":      date_to,
        "week_number":  week_number,
        "top_film":     top_film,
        "top_total":    top_total,
        "change_pct":   change_pct,
        "is_estimates": is_estimates,
    }
    weekends.append(summary)

    # Sort descending
    weekends.sort(key=lambda w: w["date_from"], reverse=True)

    save_json("weekends.json", {
        "updated":  datetime.now().isoformat(),
        "weekends": weekends,
    })


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
        if len(cells) < 4:
            continue
        try:
            # The Numbers daily columns (no distributor column):
            # 0: Rank | 1: Title | 2: Daily Gross | 3: Theaters
            # 4: Avg | 5: Total Gross | 6: Days in Release

            def safe_int(s):
                try:
                    return int(s.replace(",", "").replace("#", "").strip() or 0)
                except (ValueError, AttributeError):
                    return 0

            # % change lives between gross and theaters on some pages
            # Try to detect by checking if cell[3] looks like a theater count (no $)
            raw3 = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            has_pct_col = "%" in (cells[3].get_text(strip=True) if len(cells) > 3 else "")

            if has_pct_col:
                # Layout: Rank | Title | Gross | %Chg | Theaters | Avg | Total | Days
                pct_text = cells[3].get_text(strip=True)
                try:
                    pct_change = float(pct_text.replace("%", "").replace("+", ""))
                except ValueError:
                    pct_change = None
                entry = {
                    "rank":            safe_int(cells[0].get_text(strip=True)),
                    "title":           cells[1].get_text(strip=True),
                    "movie_url":       cells[1].find("a")["href"] if cells[1].find("a") else "",
                    "distributor":     "",
                    "daily_gross":     parse_money(cells[2].get_text(strip=True)),
                    "pct_change":      pct_change,
                    "theaters":        safe_int(cells[4].get_text(strip=True)) if len(cells) > 4 else 0,
                    "avg_per_theater": parse_money(cells[5].get_text(strip=True)) if len(cells) > 5 else 0,
                    "total_gross":     parse_money(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
                    "days_in_release": safe_int(cells[7].get_text(strip=True)) if len(cells) > 7 else 0,
                }
            else:
                # Layout: Rank | Title | Gross | Theaters | Avg | Total | Days
                entry = {
                    "rank":            safe_int(cells[0].get_text(strip=True)),
                    "title":           cells[1].get_text(strip=True),
                    "movie_url":       cells[1].find("a")["href"] if cells[1].find("a") else "",
                    "distributor":     "",
                    "daily_gross":     parse_money(cells[2].get_text(strip=True)),
                    "pct_change":      None,
                    "theaters":        safe_int(cells[3].get_text(strip=True)),
                    "avg_per_theater": parse_money(cells[4].get_text(strip=True)) if len(cells) > 4 else 0,
                    "total_gross":     parse_money(cells[5].get_text(strip=True)) if len(cells) > 5 else 0,
                    "days_in_release": safe_int(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
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
        # Find the most recently COMPLETED weekend's Friday
        today = datetime.now()
        days_since_friday = (today.weekday() - 4) % 7
        date = today - timedelta(days=days_since_friday)
        # Go back one more week if:
        #   - It's Friday or Saturday (current weekend just started, data not posted yet)
        #   - It's Monday morning (previous weekend data may not be posted yet)
        if today.weekday() in (4, 5) or today.weekday() < 1:
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
        if len(cells) < 4:
            continue
        try:
            # The Numbers weekend columns (no distributor column):
            # 0: Rank | 1: Title | 2: Weekend Gross | 3: Theaters
            # 4: % Change | 5: Avg | 6: Total Gross | 7: Week #

            change_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
            # New releases show "-" or blank, not "NEW"
            is_new = change_text in ("", "-", "n/a") or change_text.upper() == "NEW"
            try:
                change_pct = None if is_new else float(change_text.replace("%", "").replace("+", ""))
            except ValueError:
                change_pct = None

            def safe_int(s):
                try:
                    return int(s.replace(",", "").replace("#", "").strip() or 0)
                except (ValueError, AttributeError):
                    return 0

            entry = {
                "rank":             safe_int(cells[0].get_text(strip=True)),
                "title":            cells[1].get_text(strip=True),
                "movie_url":        cells[1].find("a")["href"] if cells[1].find("a") else "",
                "distributor":      "",
                "weekend_gross":    parse_money(cells[2].get_text(strip=True)),
                "theaters":         safe_int(cells[3].get_text(strip=True)),
                "change_pct":       change_pct,
                "is_new":           is_new,
                "avg_per_theater":  parse_money(cells[5].get_text(strip=True)) if len(cells) > 5 else 0,
                "total_gross":      parse_money(cells[6].get_text(strip=True)) if len(cells) > 6 else 0,
                "weeks_in_release": safe_int(cells[7].get_text(strip=True)) if len(cells) > 7 else 0,
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


# ── Enrich weekend data with derived fields ───────────────────────────────────

def enrich_weekend(current: list[dict], previous_path: str, yearly: list[dict]) -> list[dict]:
    """
    Add calculated fields to the weekend chart:
      - avg_per_theater  : weekend_gross / theaters
      - last_rank        : rank from previous weekend (None if new)
      - change_pct       : % change in gross vs previous weekend
      - theater_change   : theater count difference vs previous weekend
      - total_gross      : from year-to-date chart
      - is_new           : True if not in previous weekend's chart
    """
    # Load previous weekend for LW comparisons
    prev_by_title = {}
    try:
        with open(previous_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
        for m in prev_data.get("chart", []):
            prev_by_title[m["title"].lower()] = m
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # No previous data yet — first run

    # Build total gross lookup from yearly chart
    yearly_by_title = {}
    for m in yearly:
        yearly_by_title[m["title"].lower()] = m.get("total_gross", 0)

    enriched = []
    for m in current:
        key = m["title"].lower()
        prev = prev_by_title.get(key)

        # Average per theater
        theaters = m.get("theaters") or 0
        gross    = m.get("weekend_gross") or 0
        avg = round(gross / theaters) if theaters > 0 else 0

        # LW comparisons
        if prev:
            last_rank      = prev.get("rank")
            prev_gross     = prev.get("weekend_gross") or 0
            prev_theaters  = prev.get("theaters") or 0
            change_pct     = round((gross - prev_gross) / prev_gross * 100, 1) if prev_gross > 0 else None
            theater_change = (theaters - prev_theaters) if theaters > 0 and prev_theaters > 0 else None
            is_new         = False
        else:
            last_rank      = None
            change_pct     = None
            theater_change = None
            is_new         = True

        # Total gross from yearly chart (most accurate running total)
        total_gross = yearly_by_title.get(key) or m.get("total_gross") or 0

        enriched.append({
            **m,
            "avg_per_theater":  avg,
            "last_rank":        last_rank,
            "change_pct":       change_pct,
            "theater_change":   theater_change,
            "total_gross":      total_gross,
            "is_new":           is_new,
        })

    return enriched


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

    # Yearly chart first — needed to enrich weekend with total grosses
    yearly = scrape_yearly()
    save_json("yearly.json", {
        "updated": now.isoformat(),
        "year": now.year,
        "chart": yearly
    })

    # Determine date range for the most recently completed weekend
    today = now.date()
    days_since_friday = (today.weekday() - 4) % 7
    friday = today - timedelta(days=days_since_friday)
    if today.weekday() in (4, 5) or today.weekday() < 1:
        friday -= timedelta(days=7)
    sunday   = friday + timedelta(days=2)
    week_num = int(sunday.strftime("%U"))

    # Weekend chart — enrich with calculated fields before saving
    prev_path = os.path.join(DATA_DIR, "weekend.json")
    weekend_raw = scrape_weekend(date=datetime(friday.year, friday.month, friday.day))
    weekend_enriched = enrich_weekend(weekend_raw, prev_path, yearly)

    weekend_payload = {
        "updated":     now.isoformat(),
        "date_from":   str(friday),
        "date_to":     str(sunday),
        "week_number": week_num,
        "chart":       weekend_enriched
    }

    # Save current weekend (for homepage / fallback)
    save_json("weekend.json", weekend_payload)

    # Save per-date file so individual chart pages can load historical data
    save_json(f"weekends/{friday}.json", weekend_payload)

    # Update the master index (drives weekend.html year view)
    update_weekends_index(str(friday), str(sunday), week_num, weekend_enriched)

    print("\n" + "=" * 60)
    print("Done! JSON files written to data/")
    print("  data/daily.json")
    print("  data/weekend.json")
    print(f"  data/weekends/{friday}.json")
    print("  data/weekends.json (index updated)")
    print("  data/yearly.json")


if __name__ == "__main__":
    main()
