"""
Box Office Jedi — The Numbers Scraper
======================================
Scrapes daily and weekend box office data from The Numbers (the-numbers.com)
and outputs clean JSON files for the website to consume.

Run manually:
  python3 scrape_the_numbers.py                              # update everything
  python3 scrape_the_numbers.py --mode daily                 # only daily chart
  python3 scrape_the_numbers.py --mode weekend               # only weekend chart
  python3 scrape_the_numbers.py --mode daily --date 2026-04-17
                                                            # scrape a specific day
                                                            # (useful for backfilling)
  python3 scrape_the_numbers.py --mode daily --date 2026-04-17 --end-date 2026-04-18
                                                            # scrape an inclusive range

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
import re
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

def _norm_header(s: str) -> str:
    """Lowercase + strip everything non-alphanumeric. 'Per Theater' → 'pertheater'."""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _build_column_map(table) -> dict:
    """
    Walk the table's header row and return a {canonical_name: column_index} map.

    The Numbers' weekend chart layout (as of 2026):
      Rank | Prev | Title | Gross | Weekly Change | Theaters | Theater Average | Total Gross | Days in Release

    Rather than hard-code positions, we read the <th>/<td> header row and map each
    header to a canonical key we care about. The matcher is intentionally
    PERMISSIVE — it uses substring tests rather than exact string equality so
    header drift (e.g. "Cume" vs "Total Gross", "LW" vs "Prev") doesn't quietly
    drop a column.
    """
    # Prefer <thead>, else use the first row of the table
    header_cells = []
    thead = table.find("thead")
    if thead:
        hdr_row = thead.find("tr")
        if hdr_row:
            header_cells = hdr_row.find_all(["th", "td"])
    if not header_cells:
        first_row = table.find("tr")
        if first_row:
            header_cells = first_row.find_all(["th", "td"])

    canonical = {}
    raw_headers = []
    for i, cell in enumerate(header_cells):
        raw = cell.get_text(" ", strip=True)
        n = _norm_header(raw)
        raw_headers.append((i, raw, n))
        if not n:
            continue

        def put(key):
            canonical.setdefault(key, i)

        # ── % change column ──
        # Any header containing '%' or the substring 'change'/'chg' is a
        # percent-change column. MUST run before the yd/lw block because
        # "% YD" or "% LW" would otherwise be miscategorized.
        if "%" in raw or "change" in n or "chg" in n or n.startswith("pct"):
            put("pct_change")
            continue

        # ── rank ──
        if n in ("rank", "td") or n.startswith("rank") or n == "tw":
            put("rank")
            continue

        # ── previous-period rank (LW / YD / Prev) ──
        if (n in ("yd", "yesterday", "lw", "lastweek", "lastrank",
                  "ydyesterday", "prev", "previous", "prevrank", "prevweek")
            or n.startswith("prev") or n.startswith("last")):
            put("yd_rank")
            continue

        # ── title / release / movie ──
        if (n in ("release", "movie", "title") or n.startswith("movie")
            or n.startswith("release") or n.startswith("title")
            or "title" in n):
            put("title")
            continue

        # ── distributor / studio ── (must run before "gross" so a
        # "Distributor" header with the word "gross" elsewhere isn't grabbed)
        if n in ("distributor", "studio") or "distrib" in n or "studio" in n:
            put("distributor")
            continue

        # ── total / cumulative / to-date / cume ──
        # ANY header containing 'total' or 'cume' or 'todate' is the
        # cumulative-gross column. This catches "Total Gross", "Cume",
        # "Cumulative", "Gross to Date", "Total Box Office", etc.
        if ("total" in n or "cume" in n or "todate" in n
            or "cumul" in n or "running" in n
            or n in ("total", "totalgross", "grosstotal", "grosstotaltodate")):
            put("total")
            continue

        # ── theaters / locations ──
        if (n in ("theatres", "theaters", "locations", "location", "loc",
                  "theatrestotal")
            or n.startswith("theat") or "location" in n):
            put("theaters")
            continue

        # ── average per theater ──
        # "Theater Average", "Avg", "Per Theater", "$/Theater", etc.
        if (n in ("avg", "average", "pertheater", "perlocation", "perloc",
                  "pertheatre", "dollarsperlocation", "dollarspertheater")
            or "average" in n or n.startswith("avg") or "pertheat" in n
            or "perlocation" in n):
            put("avg")
            continue

        # ── days / weeks in release ──
        if (n in ("days", "daysinrelease", "daysinrel", "weeks", "weeksinrelease")
            or n.startswith("days") or n.startswith("weeks")
            or "inrelease" in n):
            put("days")
            continue

        # ── gross / weekend / daily (must run LAST so it doesn't grab
        # "Total Gross" — that's already been matched above) ──
        if (n in ("daily", "dailygross", "gross", "weekend", "weekendgross")
            or n == "wkndgross" or n.startswith("weekend")):
            put("gross")
            continue

    # Diagnostic logging: warn loudly about any expected column that got
    # dropped, so a silent regression on the source page surfaces in CI logs.
    expected = ("rank", "title", "gross", "theaters", "total", "days", "pct_change")
    missing  = [k for k in expected if k not in canonical]
    if missing:
        print(f"  ⚠ Column map missing {missing}. Headers were:")
        for i, raw, n in raw_headers:
            print(f"      [{i}] raw={raw!r}  norm={n!r}")

    return canonical


def _safe_int(s) -> int:
    try:
        return int(str(s).replace(",", "").replace("#", "").replace("+", "").strip() or 0)
    except (ValueError, AttributeError):
        return 0


def _safe_pct(s) -> float | None:
    """Parse a percent-change cell. Returns None if blank or not a number."""
    if not s:
        return None
    t = s.strip()
    if t in ("", "-", "--", "n/a", "N/A") or t.upper() == "NEW":
        return None
    try:
        return float(t.replace("%", "").replace("+", "").replace(",", ""))
    except ValueError:
        return None


def _norm_title(s: str) -> str:
    """Lowercase + alphanumeric only — matches the distributor_overrides keying."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def apply_daily_overrides(day_iso: str, archive_chart: list[dict]) -> list[dict]:
    """Merge data/daily_overrides.json into a freshly-scraped daily chart.
    Lets us hand-patch missing rows (e.g. Disney titles that The Numbers
    silently drops some days) without losing the fix on the next re-scrape.

    Override file shape:
        { "YYYY-MM-DD": { "add": [ {row…}, … ], "edit": { "normtitle": {field: val} } } }
    Re-ranking by daily_gross desc happens after the merge.
    """
    try:
        with open(os.path.join(DATA_DIR, "daily_overrides.json"), "r", encoding="utf-8") as f:
            overrides = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return archive_chart

    day_overrides = overrides.get(day_iso) or {}
    if not isinstance(day_overrides, dict):
        return archive_chart

    # ─── EDIT: patch fields on existing rows ───────────────────────────────
    edits = day_overrides.get("edit") or {}
    if isinstance(edits, dict):
        for row in archive_chart:
            patch = edits.get(_norm_title(row.get("title", "")))
            if isinstance(patch, dict):
                row.update(patch)

    # ─── ADD: inject rows missing from the scrape ──────────────────────────
    additions = day_overrides.get("add") or []
    if isinstance(additions, list):
        existing_keys = {_norm_title(r.get("title", "")) for r in archive_chart}
        added = 0
        for raw in additions:
            if not isinstance(raw, dict):
                continue
            t = raw.get("title")
            if not t or _norm_title(t) in existing_keys:
                # Already present (scraper picked it up after all) — skip.
                continue
            # Normalize to the same shape as scraper-written rows.
            archive_chart.append({
                "rank":            raw.get("rank", 0),
                "title":           t,
                "tmdb_id":         raw.get("tmdb_id"),
                "movie_url":       raw.get("movie_url", ""),
                "distributor":     raw.get("distributor", ""),
                "theaters":        raw.get("theaters", 0),
                "daily_gross":     raw.get("daily_gross", 0),
                "pct_change":      raw.get("pct_change"),
                "avg_per_theater": raw.get("avg_per_theater", 0),
                "total_gross":     raw.get("total_gross", 0),
                "days_in_release": raw.get("days_in_release", 0),
                "is_new":          raw.get("is_new", False),
            })
            added += 1
        if added:
            print(f"  + Applied {added} override row(s) from daily_overrides.json")

    # ─── Re-rank by daily_gross desc so injected rows land in the right spot
    archive_chart.sort(key=lambda r: r.get("daily_gross", 0) or 0, reverse=True)
    for i, r in enumerate(archive_chart, 1):
        r["rank"] = i
    return archive_chart


def apply_title_canonicalization(archive_chart: list[dict]) -> list[dict]:
    """Rewrite scraped titles to their releases.json canonical form when
    we have a strong match.

    The Numbers uses cosmetic shorthand that bites us: "The Mandalorian &
    Grogu" instead of "Star Wars: The Mandalorian and Grogu", "I.S.S."
    becoming "ISS", subtitles dropped, ampersands swapped for "and", etc.
    Each variant creates a different normalized slug, which means:
      - The movie profile page link goes to an empty page
      - The daily chart and the franchise / showdown pages don't agree
        on which film is which
      - distributor_overrides + movie_meta_overrides have to maintain
        every variant by hand

    This function scans every row, looks up the film in releases.json by
    word-overlap (same matcher as the preview filter), and if a strong
    match exists (2+ shared content words OR one shared token ≥ 7 chars),
    rewrites the row's `title` to the releases.json title. Movie_url is
    left alone — daily.html rebuilds the link from title + year anyway.
    """
    try:
        with open(os.path.join(DATA_DIR, "releases.json"), "r", encoding="utf-8") as f:
            releases = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return archive_chart

    _STOPWORDS = {
        "a", "an", "the", "and", "of", "in", "on", "to", "with", "for",
        "from", "by", "as", "at", "is", "or",
    }
    def title_tokens(s: str) -> set[str]:
        out = set()
        for raw in re.split(r"[^A-Za-z0-9]+", s or ""):
            t = raw.lower()
            if not t or t in _STOPWORDS or len(t) < 2:
                continue
            out.add(t)
        return out

    # Build list of (canonical_title, token_set) from every release.
    canonicals = []
    for month_key, month in (releases.get("months") or {}).items():
        for week in (month.get("weeks") or []):
            for r in (week.get("releases") or []):
                t = r.get("title")
                if not t:
                    continue
                toks = title_tokens(t)
                if toks:
                    canonicals.append((t, toks))

    if not canonicals:
        return archive_chart

    rewritten = 0
    for row in archive_chart:
        raw_title = row.get("title") or ""
        # Skip rows that already match a canonical exactly
        if any(raw_title == c for c, _ in canonicals):
            continue
        scraped_toks = title_tokens(raw_title)
        if not scraped_toks:
            continue
        best = None
        best_score = 0.0
        for canon, rel_toks in canonicals:
            shared = scraped_toks & rel_toks
            if not shared:
                continue
            has_strong = any(len(t) >= 7 for t in shared)
            cov_scraped = len(shared) / max(1, len(scraped_toks))
            cov_release = len(shared) / max(1, len(rel_toks))
            cov = max(cov_scraped, cov_release)
            ok = (len(shared) >= 2 and cov >= 0.5) or has_strong
            score = len(shared) + (1.0 if has_strong else 0.0) + cov
            if ok and score > best_score:
                best = canon
                best_score = score
        if best and best != raw_title:
            row["title"] = best
            # Drop the scraper's movie_url since it's based on the wrong
            # title; daily.html rebuilds the link from title + year.
            row["movie_url"] = ""
            rewritten += 1
            print(f"  ✎ Canonicalized title: {raw_title!r} -> {best!r}")

    if rewritten:
        print(f"  ✎ Rewrote {rewritten} title(s) to releases.json canonical form.")
    return archive_chart


def apply_preview_filter(day_iso: str, archive_chart: list[dict]) -> list[dict]:
    """Drop Thursday-preview rows from a daily chart.

    Industry convention (BOM, The Numbers): Thursday preview grosses are
    folded into Friday's totals, NOT counted in Thursday's daily chart.
    The Numbers' table sometimes ignores this — surfacing $5M+ preview
    rows on the day BEFORE a film officially opens. Those rows mislead
    the daily chart and have to be stripped.

    Detection rule: a row is a preview iff
        (1) data/releases.json has the film with a release_date strictly
            later than `day_iso`, AND
        (2) total_gross == daily_gross (the film has never charted before).

    Both conditions are required so a re-issue / late-blooming indie
    isn't accidentally dropped.
    """
    try:
        with open(os.path.join(DATA_DIR, "releases.json"), "r", encoding="utf-8") as f:
            releases = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return archive_chart

    # Tokenize a title into a set of "content" word-tokens, dropping common
    # stopwords + connectors. We use this for word-overlap matching to
    # handle cases where The Numbers and our releases.json disagree on
    # title formatting:
    #   "Star Wars: The Mandalorian and Grogu"  ↔  "The Mandalorian & Grogu"
    #   "Hit Me Hard and Soft - The Tour Live in 3D"  ↔  "Hit Me Hard and Soft—The Tour"
    # Without word-level matching, the normalized strings don't share
    # enough characters in the same order to pass any prefix/substring
    # test and the filter silently misses the row.
    _STOPWORDS = {
        "a", "an", "the", "and", "of", "in", "on", "to", "with", "for",
        "from", "by", "as", "at", "is", "or",
    }
    def title_tokens(s: str) -> set[str]:
        # Split on whitespace and any non-alphanumeric (so "&" and ":" act
        # as separators, not glyphs that vanish silently into adjacent
        # tokens). Lowercase each token and drop stopwords + very short
        # tokens (length 1 like "I", or "II"/"3D" survives because len>=2).
        out = set()
        for raw in re.split(r"[^A-Za-z0-9]+", s or ""):
            t = raw.lower()
            if not t or t in _STOPWORDS or len(t) < 2:
                continue
            out.add(t)
        return out

    # Walk every release in releases.json. For each, store:
    #   norm_title → (release_date, token_set)
    # so the lookup can fall back to word-overlap when string matching fails.
    release_records = {}
    for month_key, month in (releases.get("months") or {}).items():
        for week in (month.get("weeks") or []):
            wk_date = week.get("date") or ""
            for r in (week.get("releases") or []):
                t = r.get("title")
                if not t:
                    continue
                rd = r.get("release_date") or wk_date
                if not rd:
                    continue
                key = _norm_title(t)
                if not key:
                    continue
                toks = title_tokens(t)
                existing = release_records.get(key)
                if existing is None or rd < existing[0]:
                    release_records[key] = (rd, toks)

    if not release_records:
        return archive_chart

    title_to_release = {k: v[0] for k, v in release_records.items()}

    def lookup_release(nk: str, raw_title: str) -> str | None:
        """Find the earliest release_date for a film. Tries exact match,
        'the' prefix strip, prefix matching (truncated subtitle case), and
        finally word-overlap matching (handles "Star Wars: The Mandalorian
        and Grogu" ↔ "The Mandalorian & Grogu" — same film, totally
        different normalized strings)."""
        if not nk:
            return None
        # 1. Exact
        if nk in title_to_release:
            return title_to_release[nk]
        # 2. 'the' stripped on the scraped side
        if nk.startswith("the"):
            stripped = nk[3:]
            if stripped in title_to_release:
                return title_to_release[stripped]
        # 3. Prefix-of: scraped norm is a prefix of a releases.json norm
        #    (catches truncated subtitles). Require min 12 chars to avoid
        #    "thecrow" matching "thecrowdeluxecollectionedition".
        if len(nk) >= 12:
            best = None
            for k, rd in title_to_release.items():
                if k.startswith(nk) and (best is None or rd < best):
                    best = rd
            if best:
                return best
        # 4. Prefix-of (other direction): a releases.json norm is a prefix
        #    of the scraped norm (catches expanded subtitles in scrape).
        if len(nk) >= 12:
            best = None
            for k, rd in title_to_release.items():
                if len(k) >= 12 and nk.startswith(k):
                    if best is None or rd < best:
                        best = rd
            if best:
                return best
        # 5. Word-overlap: tokenize raw_title, find a releases.json entry
        #    whose token set shares enough content with it. A "match" is:
        #      - At least 2 shared non-stopword tokens, OR
        #      - 1 shared token ≥ 7 chars (highly distinctive proper noun
        #        like "mandalorian" — single match is enough)
        #    AND the shared tokens cover ≥ 60% of either side's tokens
        #    (so a passing reference like "Mandalorian" in some other
        #    film's subtitle doesn't accidentally pull in the wrong rd).
        scraped_toks = title_tokens(raw_title)
        if not scraped_toks:
            return None
        best = None
        best_score = 0
        for k, (rd, rel_toks) in release_records.items():
            if not rel_toks:
                continue
            shared = scraped_toks & rel_toks
            if not shared:
                continue
            # Strong-token shortcut: any shared token ≥ 7 chars is
            # essentially a unique proper noun ("mandalorian", "obsession",
            # "thunderbolts"). One is enough.
            has_strong = any(len(t) >= 7 for t in shared)
            # Coverage on each side
            cov_scraped = len(shared) / max(1, len(scraped_toks))
            cov_release = len(shared) / max(1, len(rel_toks))
            cov = max(cov_scraped, cov_release)
            score = len(shared) + (1.0 if has_strong else 0.0) + cov
            ok = (len(shared) >= 2 and cov >= 0.5) or has_strong
            if ok and score > best_score:
                best = rd
                best_score = score
        return best

    keep = []
    dropped = []
    for row in archive_chart:
        raw_title = row.get("title", "") or ""
        nk = _norm_title(raw_title)
        rd = lookup_release(nk, raw_title)
        is_first_appearance = (
            row.get("total_gross") is not None
            and row.get("daily_gross") is not None
            and row.get("total_gross") == row.get("daily_gross")
        )
        if rd and rd > day_iso and is_first_appearance:
            dropped.append((row.get("title"), row.get("daily_gross"), rd))
            continue
        keep.append(row)

    if dropped:
        print(f"  ✕ Stripped {len(dropped)} preview row(s) on {day_iso} "
              f"(opens later, total==daily):")
        for title, gross, rd in dropped:
            print(f"      − {title:<45}  ${gross:>10,}  (release_date {rd})")
        # Re-rank by daily_gross desc
        keep.sort(key=lambda r: r.get("daily_gross", 0) or 0, reverse=True)
        for i, r in enumerate(keep, 1):
            r["rank"] = i

    return keep


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

    col = _build_column_map(table)
    print(f"  Header map: {col}")

    # Safety check — if we somehow didn't find title + gross columns, bail with
    # a clear message rather than writing garbage JSON.
    if "title" not in col or "gross" not in col:
        print("  ⚠ Could not find Title or Gross columns in header. "
              "The Numbers' layout may have changed again — aborting daily scrape.")
        return []

    # Iterate body rows. A 'row' is only a data row if it has enough <td>s.
    rows = table.find_all("tr")
    results = []

    def get_cell(cells, key, default=""):
        i = col.get(key)
        if i is None or i >= len(cells):
            return default
        return cells[i].get_text(" ", strip=True)

    for row in rows:
        cells = row.find_all("td")
        # Header/footer rows usually have <th> only or too few cells
        if len(cells) < 3:
            continue
        try:
            title_idx = col["title"]
            if title_idx >= len(cells):
                continue
            title_cell = cells[title_idx]
            title = title_cell.get_text(" ", strip=True)
            if not title:
                continue

            # The Numbers appends a summary row at the bottom of daily tables that
            # looks like "Reporting: 29" in the title column. Filter it out.
            if title.lower().startswith("reporting"):
                continue

            link = title_cell.find("a")
            movie_url = link["href"] if link and link.has_attr("href") else ""

            daily_gross = parse_money(get_cell(cells, "gross"))
            if daily_gross <= 0:
                # Rows with no dollar figure are usually header/footer artifacts
                continue

            entry = {
                "rank":            _safe_int(get_cell(cells, "rank")),
                "title":           title,
                "movie_url":       movie_url,
                "distributor":     get_cell(cells, "distributor"),
                "daily_gross":     daily_gross,
                "pct_change":      _safe_pct(get_cell(cells, "pct_change")),
                "theaters":        _safe_int(get_cell(cells, "theaters")),
                "avg_per_theater": parse_money(get_cell(cells, "avg")),
                "total_gross":     parse_money(get_cell(cells, "total")),
                "days_in_release": _safe_int(get_cell(cells, "days")),
            }
            results.append(entry)
        except (ValueError, TypeError, KeyError) as e:
            print(f"  Skipped row due to {type(e).__name__}: {e}")
            continue

    # If ranks are blank for most rows (The Numbers only shows rank for top
    # few), fill them in from position.
    ranked = [e for e in results if e["rank"] > 0]
    if len(ranked) < len(results) / 2 and results:
        for i, e in enumerate(results, start=1):
            if e["rank"] <= 0:
                e["rank"] = i

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

    col = _build_column_map(table)
    print(f"  Header map: {col}")

    if "title" not in col or "gross" not in col:
        print("  ⚠ Could not find Title or Gross columns in header. "
              "The Numbers' layout may have changed again — aborting weekend scrape.")
        return []

    def get_cell(cells, key, default=""):
        i = col.get(key)
        if i is None or i >= len(cells):
            return default
        return cells[i].get_text(" ", strip=True)

    rows = table.find_all("tr")
    results = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        try:
            title_idx = col["title"]
            if title_idx >= len(cells):
                continue
            title = cells[title_idx].get_text(" ", strip=True)
            if not title or title.lower().startswith("reporting"):
                continue

            gross = parse_money(get_cell(cells, "gross"))
            if gross <= 0:
                continue

            change_text = get_cell(cells, "pct_change")
            is_new = change_text in ("", "-", "--", "n/a") or change_text.upper() == "NEW"
            change_pct = _safe_pct(change_text)

            link = cells[title_idx].find("a")
            movie_url = link["href"] if link and link.has_attr("href") else ""

            entry = {
                "rank":             _safe_int(get_cell(cells, "rank")),
                "title":            title,
                "movie_url":        movie_url,
                "distributor":      get_cell(cells, "distributor"),
                "weekend_gross":    gross,
                "theaters":         _safe_int(get_cell(cells, "theaters")),
                "change_pct":       change_pct,
                "is_new":           is_new,
                "avg_per_theater":  parse_money(get_cell(cells, "avg")),
                "total_gross":      parse_money(get_cell(cells, "total")),
                "weeks_in_release": _safe_int(get_cell(cells, "days")),
            }
            results.append(entry)
        except (ValueError, TypeError, KeyError) as e:
            print(f"  Skipped row due to {type(e).__name__}: {e}")
            continue

    # Fill in sequential ranks if ranks column is blank for most rows
    ranked = [e for e in results if e["rank"] > 0]
    if len(ranked) < len(results) / 2 and results:
        for i, e in enumerate(results, start=1):
            if e["rank"] <= 0:
                e["rank"] = i

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

def _norm_title_key(s: str) -> str:
    """Lowercase + strip non-alphanumeric. Used to match titles between
    sources that disagree on punctuation (curly vs. straight apostrophes,
    "&" vs. "and", etc.)."""
    import re
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _archive_first_seen() -> dict:
    """Scan all weekend files and return {movie_url_or_titlekey: earliest date_from}.
    Used to determine whether a film on the current weekend is *truly* new
    (its first ever appearance in our archive) or an expansion / re-release /
    chart re-entry.
    """
    import glob
    first_seen = {}
    weekend_dir = os.path.join(DATA_DIR, "weekends")
    files = sorted(glob.glob(os.path.join(weekend_dir, "*.json")))
    # Pass 1: build title->url cache so re-keying is stable across weeks
    url_for_title = {}
    for path in files:
        if os.path.basename(path) == "index.json":
            continue
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        for row in (d.get("chart") or []):
            tk = _norm_title_key(row.get("title"))
            url = (row.get("movie_url") or "").strip()
            if tk and url and tk not in url_for_title:
                url_for_title[tk] = url
    # Pass 2: build first-seen map keyed by url (preferred) or title
    for path in files:
        if os.path.basename(path) == "index.json":
            continue
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        date_from = d.get("date_from") or ""
        if not date_from:
            continue
        for row in (d.get("chart") or []):
            url = (row.get("movie_url") or "").strip()
            if not url:
                tk = _norm_title_key(row.get("title"))
                url = url_for_title.get(tk, "")
            key = url or _norm_title_key(row.get("title"))
            if not key:
                continue
            if key not in first_seen or date_from < first_seen[key]:
                first_seen[key] = date_from
    return first_seen, url_for_title


def enrich_weekend(current: list[dict], previous_path: str, yearly: list[dict],
                   current_friday_str: str = "") -> list[dict]:
    """
    Add calculated fields to the weekend chart:
      - avg_per_theater  : weekend_gross / theaters
      - last_rank        : rank from previous weekend (None if no LW data)
      - change_pct       : % change in gross vs previous weekend
      - theater_change   : theater count difference vs previous weekend
      - total_gross      : from year-to-date chart, falling back to a
                           normalized-title match, then to whatever the
                           weekend row itself reported
      - is_new           : True ONLY if this is the film's first appearance
                           anywhere in our weekend archive (re-releases,
                           expansions, and chart re-entries are NOT new)
      - weeks_in_release : number of weekends (1-indexed) since the film's
                           first archive appearance, inclusive of this one.
                           Requires `current_friday_str`.
    """
    prev_by_title = {}
    try:
        with open(previous_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
        for m in prev_data.get("chart", []):
            prev_by_title[_norm_title_key(m["title"])] = m
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Two yearly maps: by raw lowercased title (legacy) and by normalized
    # alphanumeric-only title (catches curly-apostrophe / & vs and mismatches).
    yearly_by_title_raw  = {}
    yearly_by_title_norm = {}
    for m in yearly:
        title = m.get("title") or ""
        yearly_by_title_raw[title.lower()]      = m.get("total_gross", 0)
        yearly_by_title_norm[_norm_title_key(title)] = m.get("total_gross", 0)

    # Build the archive first-seen map ONCE per run.
    archive_first_seen, archive_url_for_title = _archive_first_seen()

    enriched = []
    for m in current:
        title    = m.get("title") or ""
        norm_key = _norm_title_key(title)
        prev = prev_by_title.get(norm_key)

        theaters = m.get("theaters") or 0
        gross    = m.get("weekend_gross") or 0
        avg = round(gross / theaters) if theaters > 0 else 0

        if prev:
            last_rank      = prev.get("rank")
            prev_gross     = prev.get("weekend_gross") or 0
            prev_theaters  = prev.get("theaters") or 0
            change_pct     = round((gross - prev_gross) / prev_gross * 100, 1) if prev_gross > 0 else None
            theater_change = (theaters - prev_theaters) if theaters > 0 and prev_theaters > 0 else None
        else:
            last_rank      = None
            change_pct     = None
            theater_change = None

        # ── is_new: archive-aware ──
        # We're appending THIS weekend's data to the archive after this run,
        # so to test "first ever appearance," we ask: does the archive
        # already know about this film from a date BEFORE today?
        url = (m.get("movie_url") or "").strip()
        if not url:
            url = archive_url_for_title.get(norm_key, "")
        film_key = url or norm_key
        prior_date = archive_first_seen.get(film_key)
        # The current weekend's date_from isn't known here, but if a prior
        # archive date exists for this film, it's definitely not new.
        # Conservatively: is_new iff archive has NO prior record for it.
        is_new = (prior_date is None)

        # ── total_gross: yearly chart with normalized fallback ──
        total_gross = (
            yearly_by_title_raw.get(title.lower())
            or yearly_by_title_norm.get(norm_key)
            or m.get("total_gross")
            or 0
        )

        # ── weeks_in_release: count weekends from first archive
        # appearance (inclusive). New films get 1.
        weeks_in_release = m.get("weeks_in_release") or 0
        if current_friday_str:
            anchor = prior_date or current_friday_str
            try:
                d_first = datetime.strptime(anchor, "%Y-%m-%d")
                d_now   = datetime.strptime(current_friday_str, "%Y-%m-%d")
                weeks_in_release = max(1, ((d_now - d_first).days // 7) + 1)
            except Exception:
                pass

        enriched.append({
            **m,
            "avg_per_theater":  avg,
            "last_rank":        last_rank,
            "change_pct":       change_pct,
            "theater_change":   theater_change,
            "total_gross":      total_gross,
            "is_new":           is_new,
            "weeks_in_release": weeks_in_release,
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
    parser.add_argument(
        "--date",
        default=None,
        help=(
            "Scrape a specific date (YYYY-MM-DD). "
            "In daily mode this scrapes the given day (useful for backfilling). "
            "In weekend mode this should be the Friday of the target weekend."
        ),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help=(
            "Inclusive end of a daily date range (YYYY-MM-DD). "
            "Only valid with --mode daily and --date. "
            "Example: --date 2026-04-17 --end-date 2026-04-18."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the weekend-actuals protection rule. Use this when "
            "re-scraping a weekend whose stored file is incomplete (e.g. "
            "missing Total Gross or Days in Release columns)."
        ),
    )
    args = parser.parse_args()

    now = datetime.now()
    print(f"Box Office Jedi Scraper — {now.strftime('%Y-%m-%d %H:%M:%S')} — mode: {args.mode}")
    print("=" * 60)

    # Build the list of days we'll scrape in daily mode
    daily_dates = []
    if args.date:
        try:
            start_d = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"  --date must be YYYY-MM-DD, got: {args.date}")
            return
        if args.end_date:
            try:
                end_d = datetime.strptime(args.end_date, "%Y-%m-%d")
            except ValueError:
                print(f"  --end-date must be YYYY-MM-DD, got: {args.end_date}")
                return
            if end_d < start_d:
                print("  --end-date is before --date; nothing to do.")
                return
            d = start_d
            while d <= end_d:
                daily_dates.append(d)
                d += timedelta(days=1)
        else:
            daily_dates.append(start_d)
    else:
        # Default: yesterday only
        daily_dates.append(now - timedelta(days=1))

    # ── Daily chart ────────────────────────────────────────────────
    if args.mode in ("daily", "all"):
        for _target in daily_dates:
            daily = scrape_daily(_target)
            if daily:
                day_iso = _target.strftime("%Y-%m-%d")

                # 1) Per-day archive file — this is what daily.html reads.
                #    Normalize to the same shape the hand-filled files use.
                archive_chart = []
                for row in daily:
                    archive_chart.append({
                        "rank":            row.get("rank"),
                        "title":           row.get("title"),
                        "tmdb_id":         None,
                        "movie_url":       row.get("movie_url", ""),
                        "distributor":     row.get("distributor", ""),
                        "theaters":        row.get("theaters"),
                        "daily_gross":     row.get("daily_gross"),
                        "pct_change":      row.get("pct_change"),
                        "avg_per_theater": row.get("avg_per_theater"),
                        "total_gross":     row.get("total_gross"),
                        "days_in_release": row.get("days_in_release"),
                        "is_new":          False,
                    })

                # Strip Thursday-preview rows for films opening LATER than
                # the scrape date. Industry convention is to fold previews
                # into Friday's gross, not surface them as their own row.
                # The Numbers ignores this rule sometimes; we enforce it.
                archive_chart = apply_preview_filter(day_iso, archive_chart)

                # Canonicalize titles against releases.json (e.g. "The
                # Mandalorian & Grogu" → "Star Wars: The Mandalorian and
                # Grogu"). The Numbers uses cosmetic shorthand that breaks
                # our slug system; this rewrites to the user-curated form.
                archive_chart = apply_title_canonicalization(archive_chart)

                # Merge in any hand-patched rows for this date (Disney late-
                # reporting fixes, etc.) Re-applied automatically on every
                # re-scrape so they're never lost.
                pre_count = len(archive_chart)
                archive_chart = apply_daily_overrides(day_iso, archive_chart)

                # 2) Legacy "latest" flat file. Mirror the override-merged chart
                #    so the homepage widget never shows fewer films than the
                #    archive. Only overwrite if we're on the newest date — when
                #    backfilling older days, leave daily.json alone.
                existing_latest = load_json("daily.json") or {}
                existing_latest_date = existing_latest.get("date", "")
                if day_iso >= existing_latest_date:
                    save_json("daily.json", {
                        "updated": now.isoformat(),
                        "date":    day_iso,
                        "chart":   archive_chart,
                    })
                else:
                    print(f"  (daily.json stays on {existing_latest_date}; "
                          f"{day_iso} is older)")

                # ── Sanity check: warn if we dropped more than 3 rows
                # day-over-day. Catches silent scraper failures (Disney
                # missing, table format change, etc.) before they ship.
                try:
                    prior_iso = (_target - timedelta(days=1)).strftime("%Y-%m-%d")
                    prior = load_json(f"daily/{prior_iso}.json") or {}
                    prior_n = len(prior.get("chart") or [])
                    if prior_n and len(archive_chart) < prior_n - 3:
                        print(f"  ⚠ Row count dropped: {prior_iso}={prior_n} → "
                              f"{day_iso}={len(archive_chart)}. Likely a silent "
                              f"scrape miss — check daily_overrides.json or re-run.")
                except Exception:
                    pass

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
                # Keep 'updated' as the newest date we know about
                idx["updated"] = max(dates)
                os.makedirs(os.path.dirname(idx_path), exist_ok=True)
                with open(idx_path, "w", encoding="utf-8") as f:
                    json.dump(idx, f, indent=2)
                print(f"  → wrote daily/{day_iso}.json and updated daily/index.json")
            else:
                print("  No daily data — skipping save.")

    # ── Weekend chart ───────────────────────────────────────────────
    if args.mode in ("weekend", "all"):

        today = now.date()
        if args.date:
            try:
                friday = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(f"  --date must be YYYY-MM-DD, got: {args.date}")
                return
        else:
            # Determine the most recent Friday with available data
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

        # is_estimates: True on Sunday (estimates day), False Mon+ (actuals confirmed).
        # When --date is used for a historical backfill, treat as actuals.
        # weekday(): 0=Mon, 1=Tue, ..., 6=Sun
        is_estimates = (not args.date) and (today.weekday() == 6)

        print(f"\n[Weekend] Target: {friday_str} → {sunday}")
        print(f"          is_estimates: {is_estimates} "
              f"({'Sunday estimates run' if is_estimates else 'Monday+ actuals run'})")

        # Protection check before scraping (skipped with --force)
        if args.force:
            ok, reason = True, "FORCE flag passed; protection bypassed."
        else:
            ok, reason = should_update_weekend(friday_str, is_estimates)

        # Historical re-scrape signal: when --force AND --date are both set,
        # we're targeting a specific past weekend. Don't touch master files
        # (weekend.json / weekends.json / yearly.json) — those describe the
        # current state of the site, not the past. Only update the per-date
        # weekend file.
        historical_rescrape = bool(args.force and args.date)

        if not ok:
            print(f"\n[Weekend] SKIPPED — {reason}")
        else:
            print(f"\n[Weekend] Proceeding — {reason}")
            if historical_rescrape:
                print("[Weekend] Historical re-scrape mode: only the "
                      "per-date file will be updated; master files left alone.")

            # Yearly chart needed to enrich weekend with running totals.
            # In historical-rescrape mode, scrape it locally for enrichment
            # but do NOT write it to disk — the workflow rebuilds yearly.json
            # afterwards from the freshly-updated weekend files.
            yearly = scrape_yearly()
            if yearly and not historical_rescrape:
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
                weekend_enriched = enrich_weekend(
                    weekend_raw, prev_path, yearly if yearly else [],
                    current_friday_str=friday_str,
                )

                weekend_payload = {
                    "updated":      now.isoformat(),
                    "date_from":    friday_str,
                    "date_to":      str(sunday),
                    "week_number":  week_num,
                    "is_estimates": is_estimates,
                    "chart":        weekend_enriched,
                }

                # Save per-date file (individual chart pages + nav)
                save_json(f"weekends/{friday_str}.json", weekend_payload)

                # Keep data/weekends/index.json in sync — weekend-chart.html
                # reads this for its Last/Next Weekend navigation. Without
                # this, newly-scraped weekends get marooned (the latest
                # weekend's "Last Weekend" link will skip backwards to
                # whatever the most recently-indexed date was, dropping
                # everything in between). Earlier versions of the scraper
                # only maintained weekends.json (the master year-view
                # index), not weekends/index.json (the navigation index).
                wnav_path = os.path.join(DATA_DIR, "weekends", "index.json")
                try:
                    with open(wnav_path, "r", encoding="utf-8") as f:
                        wnav = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    wnav = {"dates": []}
                wnav_dates = set(wnav.get("dates") or [])
                wnav_dates.add(friday_str)
                wnav["dates"] = sorted(wnav_dates)
                os.makedirs(os.path.dirname(wnav_path), exist_ok=True)
                with open(wnav_path, "w", encoding="utf-8") as f:
                    json.dump(wnav, f, indent=2)

                # Master files only get updated for "live" runs. Historical
                # re-scrapes target a specific past weekend and shouldn't
                # touch the homepage's latest snapshot or master index.
                if not historical_rescrape:
                    # Save current weekend (homepage Top 5 + fallback)
                    save_json("weekend.json", weekend_payload)
                    # Update master index (drives weekend.html year view)
                    update_weekends_index(
                        friday_str, str(sunday), week_num,
                        weekend_enriched, is_estimates=is_estimates
                    )

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
