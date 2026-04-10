"""
Box Office Jedi — Weekend Data Enrichment
==========================================
Calculates derived fields for ALL historical weekend chart files by
looking backward through the data chronologically:

  last_rank      : rank from previous weekend appearance (None if new)
  change_pct     : % change in weekend gross vs previous appearance
  theater_change : theater count difference vs previous appearance
  weeks_in_release: how many weekends this title has appeared (1 = opening)
  is_new         : True if this is the title's first ever appearance

Run this any time new weekend files are added. It is safe to run repeatedly.

Usage:
    python3 scripts/enrich_weekends.py
"""

import json
import os
import glob
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
WEEKENDS_DIR = os.path.join(DATA_DIR, "weekends")


def normalize(title: str) -> str:
    """Lowercase + strip for consistent title matching."""
    return title.lower().strip()


def main():
    # ── Load all weekend files, sorted oldest → newest ────────────────────────
    pattern = os.path.join(WEEKENDS_DIR, "????-??-??.json")
    files = sorted(glob.glob(pattern))  # lexicographic = chronological for YYYY-MM-DD

    print(f"Box Office Jedi — Weekend Enrichment")
    print(f"Found {len(files)} weekend files\n")

    # ── First pass: load all charts into memory ────────────────────────────────
    weekends = []
    for filepath in files:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            date_from = data.get("date_from", "")
            chart = data.get("chart", [])
            if date_from and chart:
                weekends.append({
                    "date":     date_from,
                    "data":     data,
                    "filepath": filepath,
                })
        except (json.JSONDecodeError, OSError):
            print(f"  ⚠ Skipped (unreadable): {filepath}")
            continue

    print(f"Loaded {len(weekends)} weekends with chart data")

    # ── Build per-title history as we walk forward in time ────────────────────
    # history[normalized_title] = list of {date, rank, gross, theaters}
    history = {}

    enriched_files = 0
    enriched_entries = 0

    for weekend in weekends:
        date     = weekend["date"]
        data     = weekend["data"]
        filepath = weekend["filepath"]
        chart    = data.get("chart", [])

        new_chart = []

        for entry in chart:
            title    = entry.get("title", "")
            key      = normalize(title)
            rank     = entry.get("rank") or 0
            gross    = entry.get("weekend_gross") or 0
            theaters = entry.get("theaters") or 0

            prior = history.get(key, [])

            if not prior:
                # ── First ever appearance ──────────────────────────────────
                last_rank      = None
                change_pct     = None
                theater_change = None
                weeks          = 1
                is_new         = True
            else:
                last           = prior[-1]
                last_rank      = last["rank"]
                last_gross     = last["gross"]
                last_theaters  = last["theaters"]

                if last_gross and last_gross > 0 and gross > 0:
                    change_pct = round((gross - last_gross) / last_gross * 100, 1)
                else:
                    change_pct = None

                if theaters > 0 and last_theaters > 0:
                    theater_change = theaters - last_theaters
                else:
                    theater_change = None

                weeks  = len(prior) + 1
                is_new = False

            new_entry = {
                **entry,
                "last_rank":      last_rank,
                "change_pct":     change_pct,
                "theater_change": theater_change,
                "weeks_in_release": weeks,
                "is_new":         is_new,
            }
            new_chart.append(new_entry)
            enriched_entries += 1

            # Record this appearance in history
            if key not in history:
                history[key] = []
            history[key].append({
                "date":     date,
                "rank":     rank,
                "gross":    gross,
                "theaters": theaters,
            })

        # Write enriched file back
        data["chart"] = new_chart
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        enriched_files += 1

        if enriched_files % 200 == 0:
            print(f"  ... {enriched_files} files processed")

    # ── Also enrich data/weekend.json if it has chart data ────────────────────
    current_path = os.path.join(DATA_DIR, "weekend.json")
    try:
        with open(current_path, encoding="utf-8") as f:
            current = json.load(f)
        date_from = current.get("date_from", "")
        # Only re-enrich if its per-date file was just processed
        per_date_path = os.path.join(WEEKENDS_DIR, f"{date_from}.json")
        if os.path.exists(per_date_path):
            with open(per_date_path, encoding="utf-8") as f:
                enriched_current = json.load(f)
            with open(current_path, "w", encoding="utf-8") as f:
                json.dump(enriched_current, f, indent=2, ensure_ascii=False)
            print(f"\n  ✓ Also updated data/weekend.json ({date_from})")
    except (json.JSONDecodeError, OSError):
        pass

    print(f"\n{'='*50}")
    print(f"✓ Enriched {enriched_files} weekend files")
    print(f"✓ Processed {enriched_entries} chart entries")
    print(f"✓ Tracked {len(history)} unique movie titles")
    print(f"\nFields updated in every entry:")
    print(f"  last_rank       — previous weekend rank (None = new release)")
    print(f"  change_pct      — % gross change vs prior weekend")
    print(f"  theater_change  — theater count change vs prior weekend")
    print(f"  weeks_in_release— weeks on chart (1 = opening weekend)")
    print(f"  is_new          — True if first ever appearance")


if __name__ == "__main__":
    main()
