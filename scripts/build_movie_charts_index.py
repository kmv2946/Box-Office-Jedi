#!/usr/bin/env python3
"""
Box Office Jedi — Movie Charts Index Builder
==============================================
Walks every all-time chart in `data/charts/*.json` and, for each row,
records the film's rank on that chart. Output:

    data/movie_charts.json
    {
      "updated":  "...",
      "by_slug":  { "thedevilwearsprada-2006": [{chart, href, rank}, ...] },
      "by_title": { "thedevilwearsprada":      [{chart, href, rank}, ...] }
    }

The movie profile page reads this map to render the "Charts" panel —
e.g. "Movies That Never Hit #1 — #92" appears automatically on the
Devil Wears Prada page because the script saw that film at rank 92 of
that chart's rows.

Run:
    python3 scripts/build_movie_charts_index.py
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime


CHARTS_DIR = "data/charts"
OUT_PATH   = "data/movie_charts.json"


def norm_title(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def find_col(columns, *patterns):
    """Return the first column index whose header matches any pattern (regex)."""
    for i, c in enumerate(columns or []):
        c_lower = (c or '').lower().strip()
        for pat in patterns:
            if re.search(pat, c_lower):
                return i
    return -1


def parse_year(s):
    """Pull a 4-digit year out of any cell that looks like one."""
    if not s:
        return None
    m = re.search(r'(19|20)\d{2}', str(s))
    return int(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    files = sorted(p for p in glob.glob(os.path.join(CHARTS_DIR, '*.json'))
                   if os.path.basename(p) != 'index.json')

    by_slug = {}
    by_title = {}
    files_seen = 0
    rows_seen  = 0

    for path in files:
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        files_seen += 1
        slug = os.path.basename(path).replace('.json', '')
        label = d.get('label') or slug
        href  = f"alltime-chart.html?chart={slug}"
        columns = d.get('columns') or []
        rows    = d.get('rows') or []

        rank_col  = find_col(columns, r'^\s*rank\s*$', r'^\s*#\s*$')
        title_col = find_col(columns, r'title|release|movie')
        year_col  = find_col(columns, r'^\s*year\s*$', r'date')

        if title_col < 0:
            # Fall back: assume column 1 is the title (typical: rank, title, ...)
            title_col = 1 if len(columns) > 1 else 0

        for i, row in enumerate(rows):
            if not row or len(row) <= title_col:
                continue
            title = (row[title_col] or '').strip() if isinstance(row[title_col], str) else str(row[title_col])
            if not title:
                continue
            rank = None
            if rank_col >= 0 and rank_col < len(row):
                m = re.search(r'\d+', str(row[rank_col]))
                if m:
                    rank = int(m.group(0))
            if rank is None:
                rank = i + 1
            year = None
            if year_col >= 0 and year_col < len(row):
                year = parse_year(row[year_col])

            entry = {'chart': label, 'href': href, 'rank': rank}
            tk = norm_title(title)
            if not tk:
                continue
            rows_seen += 1
            by_title.setdefault(tk, []).append(entry)
            if year:
                slug_key = f"{tk}-{year}"
                by_slug.setdefault(slug_key, []).append(entry)

    # Sort each film's chart appearances by rank ascending (best first)
    def dedupe_sort(lst):
        seen = set()
        out = []
        for e in sorted(lst, key=lambda x: (x.get('rank') or 9999)):
            key = (e['chart'], e['href'])
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    by_slug  = {k: dedupe_sort(v) for k, v in by_slug.items()}
    by_title = {k: dedupe_sort(v) for k, v in by_title.items()}

    payload = {
        'updated':  datetime.now().isoformat(timespec='seconds'),
        'count':    len(by_slug) + len(by_title),
        'by_slug':  by_slug,
        'by_title': by_title,
    }

    print(f"  Scanned {files_seen} chart files, {rows_seen} ranked rows.")
    print(f"  Indexed {len(by_slug)} slug keys + {len(by_title)} title keys.")
    if args.dry_run:
        for sample in ('thedevilwearsprada', 'cars', 'titanic', 'avatar'):
            v = by_title.get(sample)
            if v:
                print(f"    {sample:25s} → {len(v)} chart(s)")
                for e in v[:3]:
                    print(f"        #{e['rank']:>4}  {e['chart']}")
        print("  (dry run — no file written)")
        return
    with open(OUT_PATH, 'w') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Wrote {OUT_PATH}")


if __name__ == '__main__':
    main()
