"""
Box Office Jedi — Distributor Index Builder
============================================
Walks every historical daily / weekend / yearly file and produces a single
flat lookup: data/distributors.json. The daily page uses this as a fallback
when an individual row's distributor field is blank — which happens often
when The Numbers' table layout changes and the scraper temporarily can't
read the Distributor column.

Output shape:
    {
      "updated": "2026-04-22T11:33:21",
      "by_title": {
        "the super mario galaxy movie": "Universal Pictures",
        "project hail mary": "Amazon MGM Studios",
        ...
      }
    }

Keys are normalized (lowercase, alphanumeric only) so lookups are robust to
punctuation and whitespace differences across sources.

Run manually:
    python3 scripts/build_distributor_index.py

Run automatically: see .github/workflows/update-data.yml
"""

import json
import os
import glob
from datetime import datetime
from collections import Counter

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def norm_title(s: str) -> str:
    """Lowercase + strip everything non-alphanumeric. Used for fuzzy matching."""
    if not s:
        return ""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def extract_rows(data):
    """Pull a flat list of row dicts out of a daily/weekend/yearly JSON file."""
    if not data:
        return []
    if isinstance(data, dict):
        for key in ("chart", "movies", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def main():
    sources = []
    sources += sorted(glob.glob(os.path.join(DATA_DIR, "daily", "*.json")))
    sources += sorted(glob.glob(os.path.join(DATA_DIR, "weekends", "*.json")))
    sources.append(os.path.join(DATA_DIR, "yearly.json"))
    sources.append(os.path.join(DATA_DIR, "weekend.json"))
    sources.append(os.path.join(DATA_DIR, "daily.json"))

    # title_norm → Counter({distributor: count})
    # We use a counter so the most-frequently-seen distributor wins (handles
    # the rare case where one stale file has a wrong value).
    votes = {}

    files_seen = 0
    rows_seen = 0

    for path in sources:
        if not os.path.exists(path):
            continue
        data = load_json(path)
        rows = extract_rows(data)
        if not rows:
            continue
        files_seen += 1
        for row in rows:
            title = row.get("title") or ""
            dist  = (row.get("distributor") or "").strip()
            if not title or not dist:
                continue
            key = norm_title(title)
            if not key:
                continue
            votes.setdefault(key, Counter())[dist] += 1
            rows_seen += 1

    by_title = {k: counter.most_common(1)[0][0] for k, counter in votes.items()}

    out_path = os.path.join(DATA_DIR, "distributors.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "updated":  datetime.now().isoformat(),
            "count":    len(by_title),
            "by_title": by_title,
        }, f, indent=2, ensure_ascii=False)

    print(f"  ✓ Scanned {files_seen} files, {rows_seen} rows.")
    print(f"  ✓ Wrote {out_path} with {len(by_title)} distributor mappings.")


if __name__ == "__main__":
    main()
