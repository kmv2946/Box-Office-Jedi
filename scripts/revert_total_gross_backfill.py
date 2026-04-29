#!/usr/bin/env python3
"""
REVERT — restore total_gross to its pre-backfill state.

The previous backfill (commit 74d2714 + 97d9576) summed weekend grosses
to approximate cumulative theatrical totals. That approximation is wrong
(misses weekday revenue + post-drop-off runs), so we're reverting it.

Strategy: for every weekend file, look up the version at git ref
`e349dc4` (the commit immediately before any total_gross backfill), and
copy each row's total_gross from there into the current file. Match
rows by movie_url first, falling back to a normalized title.

This preserves the GOOD changes from later commits — is_new flips,
weeks_in_release, page polish — while undoing only total_gross.

Run:
    python3 scripts/revert_total_gross_backfill.py --dry-run
    python3 scripts/revert_total_gross_backfill.py
"""
import argparse
import glob
import json
import os
import re
import subprocess

WEEKENDS_DIR = "data/weekends"
BEFORE_REF   = "e349dc4"   # commit immediately before total_gross backfill


def title_key(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def row_key(row):
    """Match rows between old and new versions of the same file."""
    url = (row.get("movie_url") or "").strip()
    if url:
        return ("url", url)
    return ("title", title_key(row.get("title")))


def git_show(ref: str, path: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "show", f"{ref}:{path}"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(
        p for p in glob.glob(os.path.join(WEEKENDS_DIR, "*.json"))
        if os.path.basename(p) != "index.json"
    )

    print(f"Restoring total_gross from {BEFORE_REF} across {len(files)} files...")

    reverted_cells = 0
    files_changed  = 0
    files_missing_old = 0

    for path in files:
        rel = os.path.relpath(path)
        try:
            with open(path) as f:
                cur_data = json.load(f)
        except Exception:
            continue

        old_text = git_show(BEFORE_REF, rel)
        if old_text is None:
            files_missing_old += 1
            continue
        try:
            old_data = json.loads(old_text)
        except Exception:
            continue

        old_by_key = {}
        for row in (old_data.get("chart") or []):
            old_by_key[row_key(row)] = row.get("total_gross", 0) or 0

        file_dirty = False
        for row in (cur_data.get("chart") or []):
            k = row_key(row)
            if k not in old_by_key:
                continue
            old_val = old_by_key[k]
            cur_val = row.get("total_gross") or 0
            if cur_val != old_val:
                row["total_gross"] = old_val
                reverted_cells += 1
                file_dirty = True

        if file_dirty:
            files_changed += 1
            if not args.dry_run:
                with open(path, "w") as f:
                    json.dump(cur_data, f, indent=2, ensure_ascii=False)

    print(f"Cells reverted to old total_gross: {reverted_cells}")
    print(f"Files updated:                     {files_changed}{' (DRY RUN)' if args.dry_run else ''}")
    if files_missing_old:
        print(f"Files with no pre-backfill version:{files_missing_old}")


if __name__ == "__main__":
    main()
