"""
Box Office Jedi — Build analysis index
======================================
Scans the repo root for roundup-*.html and forecast-*.html files, pulls each
article's title out of its <h1 class="article-headline"> and its date out of
the filename, and writes data/analysis.json — the file the Analysis page
reads at runtime.

Filename convention (required for auto-detection):
    roundup-<mon>-<day>-<year>.html     e.g. roundup-apr-20-2026.html
    forecast-<mon>-<day>-<year>.html    e.g. forecast-apr-18-2026.html

Any existing entries in data/analysis.json whose URL does NOT match that
auto-scan pattern (e.g. manually-added seasonals, spotlights, rewinds) are
preserved as-is, so the script is safe to rerun.

Usage (from the repo root):
    python3 scripts/build_analysis_index.py

Typical workflow:
    1. Drop a new roundup-<date>.html or forecast-<date>.html into the repo
    2. Run this script
    3. Commit + push — the Analysis tab picks it up automatically

Note: The <h1 class="article-headline"> is the source of truth for the title.
If you edit the headline on a published article, rerun this script so the
Analysis index stays in sync.
"""
import glob
import html
import json
import os
import re
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

OUTPUT = "data/analysis.json"

# Filename pattern: <type>-<mon>-<day>-<year>.html
FNAME_RE = re.compile(
    r"^(roundup|forecast)-([a-z]{3})-(\d{1,2})-(\d{4})\.html$",
    re.IGNORECASE,
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,  "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
HEADLINE_RE = re.compile(
    r'<h1[^>]*class="article-headline"[^>]*>(.*?)</h1>',
    re.IGNORECASE | re.DOTALL,
)


def parse_filename(fname):
    """Return {'type': ..., 'date': 'YYYY-MM-DD'} if the file matches, else None."""
    m = FNAME_RE.match(fname)
    if not m:
        return None
    kind, mon, day, year = m.groups()
    mnum = MONTHS.get(mon.lower())
    if not mnum:
        return None
    try:
        date = datetime(int(year), mnum, int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return None
    return {"type": kind.lower(), "date": date}


def extract_title(path):
    """Pull the plain-text contents of <h1 class='article-headline'>."""
    with open(path, "r", encoding="utf-8") as f:
        html_text = f.read()
    m = HEADLINE_RE.search(html_text)
    if not m:
        return None
    raw = m.group(1)
    stripped = re.sub(r"<[^>]+>", "", raw)
    decoded = html.unescape(stripped)
    return re.sub(r"\s+", " ", decoded).strip()


def load_existing():
    if not os.path.exists(OUTPUT):
        return []
    try:
        with open(OUTPUT, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("articles", [])
    except Exception:
        return []


def main():
    # 1. Scan for auto-tracked files (roundups + forecasts at repo root).
    auto = []
    skipped = []
    for fname in sorted(os.listdir(".")):
        info = parse_filename(fname)
        if not info:
            continue
        title = extract_title(fname)
        if not title:
            skipped.append(fname)
            continue
        auto.append({
            "date":  info["date"],
            "title": title,
            "type":  info["type"],
            "url":   fname,
        })

    # 2. Preserve any manually-curated entries (e.g. seasonals, spotlights,
    #    rewinds) whose URL doesn't match the auto-scan pattern.
    existing = load_existing()
    auto_urls = {a["url"] for a in auto}
    manual = [
        e for e in existing
        if e.get("url")
        and not FNAME_RE.match(e["url"])
        and e["url"] not in auto_urls
    ]

    merged = auto + manual
    merged.sort(key=lambda a: a.get("date", ""), reverse=True)

    out = {
        "updated":  datetime.now().strftime("%Y-%m-%d"),
        "articles": merged,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)
        f.write("\n")

    # Pretty console summary
    print(f"Wrote {OUTPUT} \u2014 {len(merged)} article(s):\n")
    for a in merged:
        print(f"  {a['date']}  [{a['type']:<9}]  {a['title']}")
    if manual:
        print(f"\nPreserved {len(manual)} manual entr{'y' if len(manual) == 1 else 'ies'} "
              "(non-standard URL).")
    if skipped:
        print("\nWARNING: skipped (no <h1 class='article-headline'> found):")
        for s in skipped:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
