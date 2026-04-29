#!/usr/bin/env python3
"""
Box Office Jedi — Restore master weekend snapshots from per-date files.

`data/weekend.json` should always point at the most recent weekend, and
`data/weekends.json` should be the master index of every weekend we have.
If something went wrong (e.g. a historical re-scrape ran with --force and
overwrote them with old data), this script regenerates both from the
per-date files in `data/weekends/`.

Run:
    python3 scripts/restore_master_snapshots.py
    python3 scripts/restore_master_snapshots.py --dry-run
"""
import argparse
import glob
import json
import os
from datetime import datetime


WEEKENDS_DIR = "data/weekends"


def latest_weekend_file():
    paths = sorted(
        p for p in glob.glob(os.path.join(WEEKENDS_DIR, "*.json"))
        if os.path.basename(p) != "index.json"
    )
    if not paths:
        return None
    # Sort by date_from inside the file (filenames are reliable too,
    # but the explicit field is safer).
    latest = None
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
        except Exception:
            continue
        date_from = d.get("date_from") or os.path.basename(p).replace(".json", "")
        if latest is None or date_from > latest[0]:
            latest = (date_from, p, d)
    return latest


def rebuild_weekends_index():
    """Walk every per-date weekend file and rebuild the master index."""
    paths = sorted(
        p for p in glob.glob(os.path.join(WEEKENDS_DIR, "*.json"))
        if os.path.basename(p) != "index.json"
    )
    weekends = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
        except Exception:
            continue
        chart = d.get("chart") or []
        if not chart:
            continue
        top10 = chart[:10]
        weekends.append({
            "date_from":    d.get("date_from") or os.path.basename(p).replace(".json", ""),
            "date_to":      d.get("date_to", ""),
            "week_number":  d.get("week_number", 0),
            "top_film":     chart[0].get("title", "—"),
            "top_total":    sum(m.get("weekend_gross", 0) for m in top10),
            "change_pct":   None,
            "is_estimates": d.get("is_estimates", False),
        })

    # Compute week-over-week change in ascending order then flip
    weekends.sort(key=lambda w: w["date_from"])
    for i, w in enumerate(weekends):
        if i > 0:
            prev = weekends[i - 1].get("top_total") or 0
            cur  = w.get("top_total") or 0
            if prev > 0 and cur:
                w["change_pct"] = round((cur - prev) / prev * 100, 1)
    weekends.sort(key=lambda w: w["date_from"], reverse=True)
    return weekends


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    latest = latest_weekend_file()
    if latest is None:
        print("No per-date weekend files found — nothing to restore.")
        return
    date_from, path, payload = latest
    print(f"Latest per-date file: {path}  (date_from={date_from})")

    if args.dry_run:
        print("(dry run) would write data/weekend.json and data/weekends.json")
        return

    # 1. weekend.json — homepage 'latest' snapshot
    with open("data/weekend.json", "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  → wrote data/weekend.json from {os.path.basename(path)}")

    # 2. weekends.json — master index
    weekends = rebuild_weekends_index()
    with open("data/weekends.json", "w") as f:
        json.dump({
            "updated":  datetime.now().isoformat(),
            "weekends": weekends,
        }, f, indent=2, ensure_ascii=False)
    print(f"  → wrote data/weekends.json ({len(weekends)} weekends)")


if __name__ == "__main__":
    main()
