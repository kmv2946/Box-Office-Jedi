"""
Box Office Jedi — The Numbers Scraper
======================================
Scrapes daily and weekend box office data from The Numbers (the-numbers.com)
and outputs clean JSON files for the website to consume.

Run manually:
  python3 scrape_the_numbers.py                  # update everything
  python3 scrape_the_numbers.py --mode daily     # only daily chart
  python3 scrape_the_numbers.py --mode weekend   # only weekend chart

Run via GitHub Actions: see .github/workflows/update-data.yml
  - Daily chart  : every day at 2 PM ET (19:00 UTC)
  - Weekend chart: Sundays and Mondays at 5 PM ET (22:00 UTC)

Output files:
  data/daily.json              — most recent daily chart
  data/weekend.json            — most recent weekend chart (homepage Top 5)
  data/weekends/YYYY-MM-DD.json — per-weekend chart file
  data/weekends.json           — master index (drives weekend.html)
  data/yearly.json             — year-to-date chart

Weekend data protection rules:
  - NEVER save weekend.json with data older than what's already there.
  - NEVER overwrite a weekends/YYYY-MM-DD.json that already has confirmed actuals
    (is_estimates: false). Estimates may still be refreshed until actuals land.
  - is_estimates is set True when running on Sunday (estimates day),
    False on Monday or later (actuals confirmed).
"""

import argparse
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


def load_json(filename: str) -> dict | None:
    """Load a JSON file from the data/ directory. Returns None if missing or invalid."""
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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
    Defaults to yesterday (since today's data posts overnight/midday).
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

    table = soup.find("table", id=lambda x: x and "box_office" in x.lower())
    if not table:
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
            def safe_int(s):
                try:
                    return int(s.replace(",", "").replace("#", "").strip() or 0)
                except (ValueError, AttributeError):
                    return 0

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
    Defaults to most recent weekend with available data.
    """
    if date is None:
        today = datetime.now()
        days_since_friday = (today.weekday() - 4) % 7
        date = today - timedelta(days=days_since_friday)
        # Go back one more week if it's Friday or Saturday
        # (current weekend just started, data not posted yet)
        # NOTE: Monday is intentionally NOT excluded here — actuals post Monday afternoon
        if today.weekday() in (4, 5):
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
            change_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
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
    prev_by_title = {}
    try:
        with open(previous_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
        for m in prev_data.get("chart", []):
            prev_by_title[m["title"].lower()] = m
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    yearly_by_title = {}
    for m in yearly:
        yearly_by_title[m["title"].lower()] = m.get("total_gross", 0)

    enriched = []
    for m in current:
        key = m["title"].lower()
        prev = prev_by_title.get(key)

        theaters = m.get("theaters") or 0
        gross    = m.get("weekend_gross") or 0
        avg = round(gross / theaters) if theaters > 0 else 0

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


# ── Weekend protection check ──────────────────────────────────────────────────

def should_update_weekend(friday_str: str, is_estimates: bool) -> tuple[bool, str]:
    """
    Returns (should_update, reason).

    Protection rules:
      1. If weekend.json already has data for a LATER weekend, don't overwrite it.
         This prevents the scraper from going backwards in time.
      2. If weekends/{friday}.json already exists with is_estimates=False (confirmed
         actuals), don't overwrite it. Actuals are final.
      3. If is_estimates=True (Sunday run) and a file already has estimates, we CAN
         refresh — estimates may improve throughout Sunday afternoon.
    """
    # Rule 1: Don't overwrite weekend.json with older data
    existing_weekend = load_json("weekend.json")
    if existing_weekend:
        existing_date = existing_weekend.get("date_from", "")
        if existing_date and existing_date > friday_str:
            return False, (
                f"weekend.json already has more recent data ({existing_date}) "
                f"than what was scraped ({friday_str}). Skipping to avoid going backwards."
            )

    # Rule 2: Don't overwrite confirmed actuals.
    # Default is_estimates to False when the field is missing — this protects
    # manually-entered data files that were created before the field existed.
    existing_per_date = load_json(f"weekends/{friday_str}.json")
    if existing_per_date and not existing_per_date.get("is_estimates", False):
        return False, (
            f"weekends/{friday_str}.json already has confirmed actuals "
            f"(is_estimates=false). Not overwriting with scraped data."
        )

    # Rule 3: Estimates can always be refreshed (is_estimates=True means Sunday run)
    if existing_per_date and existing_per_date.get("is_estimates", False) and not is_estimates:
        # Upgrading from estimates → actuals is always allowed
        return True, f"Upgrading weekends/{friday_str}.json from estimates to actuals."

    return True, "OK to update."


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Box Office Jedi scraper")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekend", "all"],
        default="all",
        help="What to update: daily chart, weekend chart, or all (default: all)",
    )
    args = parser.parse_args()

    now = datetime.now()
    print(f"Box Office Jedi Scraper — {now.strftime('%Y-%m-%d %H:%M:%S')} — mode: {args.mode}")
    print("=" * 60)

    # ── Daily chart ────────────────────────────────────────────────
    if args.mode in ("daily", "all"):
        daily = scrape_daily()
        if daily:
            day_iso = (now - timedelta(days=1)).strftime("%Y-%m-%d")

            # 1) Legacy "latest" flat file (kept for backward compatibility)
            save_json("daily.json", {
                "updated": now.isoformat(),
                "date":    day_iso,
                "chart":   daily,
            })

            # 2) Per-day archive file — this is what daily.html actually reads.
            #    Normalize to the same shape the hand-filled files use.
            archive_chart = []
            for row in daily:
                archive_chart.append({
                    "rank":            row.get("rank"),
                    "title":           row.get("title"),
                    "tmdb_id":         None,
                    "distributor":     row.get("distributor", ""),
                    "theaters":        row.get("theaters"),
                    "daily_gross":     row.get("daily_gross"),
                    "pct_change":      row.get("pct_change"),
                    "avg_per_theater": row.get("avg_per_theater"),
                    "total_gross":     row.get("total_gross"),
                    "days_in_release": row.get("days_in_release"),
                    "is_new":          False,
                })
            archive_path = os.path.join("daily", day_iso + ".json")
            save_json(archive_path, {
                "date":         day_iso,
                "is_estimates": False,
                "chart":        archive_chart,
            })

            # 3) Keep data/daily/index.json in sync so the daily page's
            #    prev/next navigation sees the new date.
            idx_path = os.path.join(DATA_DIR, "daily", "index.json")
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    idx = json.load(f)
            except Exception:
                idx = {"updated": "", "dates": []}
            dates = set(idx.get("dates", []))
            dates.add(day_iso)
            idx["dates"] = sorted(dates)
            idx["updated"] = day_iso
            os.makedirs(os.path.dirname(idx_path), exist_ok=True)
            with open(idx_path, "w", encoding="utf-8") as f:
                json.dump(idx, f, indent=2)
            print(f"  → wrote daily/{day_iso}.json and updated daily/index.json")
        else:
            print("  No daily data — skipping save.")

    # ── Weekend chart ───────────────────────────────────────────────
    if args.mode in ("weekend", "all"):

        # Determine the most recent Friday with available data
        today = now.date()
        days_since_friday = (today.weekday() - 4) % 7
        friday = today - timedelta(days=days_since_friday)
        # Go back one extra week if it's Friday or Saturday —
        # current weekend just started and data isn't posted yet.
        # Monday is NOT excluded: actuals post on Monday afternoon.
        if today.weekday() in (4, 5):
            friday -= timedelta(days=7)
        sunday   = friday + timedelta(days=2)
        week_num = int(sunday.strftime("%U"))
        friday_str = str(friday)

        # is_estimates: True on Sunday (estimates day), False Mon+ (actuals confirmed)
        # weekday(): 0=Mon, 1=Tue, ..., 6=Sun
        is_estimates = (today.weekday() == 6)

        print(f"\n[Weekend] Target: {friday_str} → {sunday}")
        print(f"          is_estimates: {is_estimates} "
              f"({'Sunday estimates run' if is_estimates else 'Monday+ actuals run'})")

        # Protection check before scraping
        ok, reason = should_update_weekend(friday_str, is_estimates)
        if not ok:
            print(f"\n[Weekend] SKIPPED — {reason}")
        else:
            print(f"\n[Weekend] Proceeding — {reason}")

            # Yearly chart needed to enrich weekend with running totals
            yearly = scrape_yearly()
            if yearly:
                save_json("yearly.json", {
                    "updated": now.isoformat(),
                    "year": now.year,
                    "chart": yearly
                })

            # Previous weekend file for LW comparisons
            prev_friday = friday - timedelta(days=7)
            prev_path = os.path.join(DATA_DIR, f"weekends/{prev_friday}.json")
            # Fall back to current weekend.json if prev file doesn't exist
            if not os.path.exists(prev_path):
                prev_path = os.path.join(DATA_DIR, "weekend.json")

            weekend_raw = scrape_weekend(
                date=datetime(friday.year, friday.month, friday.day)
            )

            if not weekend_raw:
                print("  No weekend data scraped — skipping save.")
            else:
                weekend_enriched = enrich_weekend(weekend_raw, prev_path, yearly if yearly else [])

                weekend_payload = {
                    "updated":      now.isoformat(),
                    "date_from":    friday_str,
                    "date_to":      str(sunday),
                    "week_number":  week_num,
                    "is_estimates": is_estimates,
                    "chart":        weekend_enriched,
                }

                # Save current weekend (homepage Top 5 + fallback)
                save_json("weekend.json", weekend_payload)

                # Save per-date file (individual chart pages + nav)
                save_json(f"weekends/{friday_str}.json", weekend_payload)

                # Update master index (drives weekend.html year view)
                update_weekends_index(
                    friday_str, str(sunday), week_num,
                    weekend_enriched, is_estimates=is_estimates
                )

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
