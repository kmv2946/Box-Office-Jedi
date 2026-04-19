"""
Box Office Jedi — Build per-year charts from the weekend archive
================================================================
Reads data/weekends/*.json (the ~1,633 historical weekend files) and
produces:

    data/years/<YYYY>.json   — {year, updated, chart: [ {rank, title,
                                distributor, total_gross, theaters,
                                opening_weekend, weeks} ]}

The per-year chart powers the yearly-chart.html drill-in view: click a
year on yearly.html and the rows for that year load from this file.

One movie = one row. "total_gross" is the maximum cumulative gross seen
across any of the movie's weekend archive entries — a close enough proxy
for lifetime domestic gross for charting purposes.

Run from the repo root:
    python3 scripts/build_year_charts.py
"""
import json, os, glob, re
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

WEEKENDS_DIR = "data/weekends"
YEARS_DIR    = "data/years"
os.makedirs(YEARS_DIR, exist_ok=True)

def norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())

# Step 1 — scan every weekend file, build a per-movie aggregate that also
# includes distributor + opening weekend + peak theaters.
movies = {}   # key -> dict
for path in sorted(glob.glob(os.path.join(WEEKENDS_DIR, "*.json"))):
    if path.endswith("index.json"):
        continue
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    date_from = d.get("date_from")
    if not date_from:
        continue
    for row in d.get("chart", []):
        title = row.get("title") or ""
        if not title:
            continue
        # Skip aggregated "Reporting: N" summary rows that The Numbers emits at
        # the end of a weekend chart — those are bookkeeping totals, not films.
        if title.startswith("Reporting:") or title.startswith("Reporting "):
            continue
        key = norm_title(title)
        if not key:
            continue
        m = movies.setdefault(key, {
            "title":       title,
            "distributor": "",
            "first_date":  date_from,
            "max_total":   0,
            "sum_weekend": 0,   # fallback when total_gross is missing (pre-2000 rows)
            "theaters":    0,
            "opening":     None,
            "weekends":    0,
        })
        # Keep most recent title capitalization (source can vary)
        if date_from > m.get("_latest", ""):
            m["title"]   = title
            m["_latest"] = date_from
        # First appearance = earliest date
        if date_from < m["first_date"]:
            m["first_date"] = date_from
        # Distributor: prefer non-empty
        dist = (row.get("distributor") or "").strip()
        if dist and not m["distributor"]:
            m["distributor"] = dist
        # Track biggest reported total
        tg = row.get("total_gross") or 0
        if tg > m["max_total"]:
            m["max_total"] = tg
        # Sum weekends as a fallback (weekend_gross is populated even when total_gross isn't)
        wg = row.get("weekend_gross") or 0
        m["sum_weekend"] += wg
        # Peak theater count
        th = row.get("theaters") or 0
        if th > m["theaters"]:
            m["theaters"] = th
        m["weekends"] += 1
        # Opening weekend = the earliest weekend's gross
        if m["opening"] is None or date_from <= m["first_date"]:
            m["opening"] = wg

# Step 2 — group by year of first_date, sort by total_gross desc
by_year = {}
for key, m in movies.items():
    year = m["first_date"][:4]
    by_year.setdefault(year, []).append(m)

wrote = 0
for year in sorted(by_year.keys()):
    if not year.isdigit() or int(year) < 1995 or int(year) > 2030:
        continue
    # Effective total: prefer the reported max_total; fall back to summed weekends
    # for older years where total_gross was left at 0.
    for m in by_year[year]:
        m["total_gross"] = m["max_total"] or m["sum_weekend"] or 0
    rows = sorted(by_year[year], key=lambda x: -x["total_gross"])[:200]
    chart = []
    for i, m in enumerate(rows, start=1):
        chart.append({
            "rank":           i,
            "title":          m["title"],
            "distributor":    m["distributor"] or None,
            "total_gross":    m["total_gross"] or None,
            "theaters":       m["theaters"]    or None,
            "opening_weekend":m["opening"]     or None,
            "weeks_on_chart": m["weekends"],
        })
    out_path = os.path.join(YEARS_DIR, year + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "year":    int(year),
            "updated": datetime.utcnow().isoformat(),
            "source":  "Weekend archive aggregation (data/weekends/).",
            "notes":   ("Total gross is the maximum cumulative gross observed in the weekend archive; "
                        "opening_weekend is the earliest weekend's gross. Some limited-release films "
                        "may be under-represented since they can drop off weekend charts quickly."),
            "chart":   chart,
        }, f, indent=1, ensure_ascii=False)
    wrote += 1

print(f"Wrote {wrote} per-year files to {YEARS_DIR}/")
# Spot-check
for y in ("1995", "2019", "2023", "2026"):
    p = os.path.join(YEARS_DIR, y + ".json")
    if os.path.exists(p):
        d = json.load(open(p))
        top = d["chart"][0] if d["chart"] else None
        if top:
            print(f"  {y}: #1 {top['title']} — ${top['total_gross']:,}  ({len(d['chart'])} films)")
