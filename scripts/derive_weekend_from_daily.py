"""
Box Office Jedi — Derive confirmed weekend actuals from the daily charts
========================================================================
The Numbers' WEEKEND page keeps showing the studios' Sunday estimates (round
numbers like $31,000,000) for days after the weekend, even though its DAILY
chart already carries the confirmed Sunday actual — and a film's cumulative
total on Sunday's daily row is that film's actual weekend-ending total.

So instead of waiting on the weekend page, this script rebuilds the weekend
chart from our own daily archive once Sunday's daily file has been re-scraped
as a confirmed actual (is_estimates: false, which the Monday daily run does):

    weekend gross = Sunday cumulative total - Thursday cumulative total
                    (a brand-new film with no Thursday row: the Sunday
                    cumulative total; fallback: Fri + Sat + Sun daily grosses)

It updates the existing data/weekends/YYYY-MM-DD.json in place (keeping its
rows, movie_urls, studios, weeks-in-release, last-rank), recomputes grosses,
theaters, averages, totals, % change, theater change and ranks, then flags the
file is_estimates: false. It only runs when:
  - the Friday/Saturday/Sunday daily files all exist, and Sunday's is confirmed
    (is_estimates: false), and
  - the weekend file is missing or still flagged is_estimates: true.
It never touches a weekend file that is already confirmed.

Usage:
  python3 scripts/derive_weekend_from_daily.py            # newest eligible weekend
  python3 scripts/derive_weekend_from_daily.py 2026-10-16 # specific Friday (forces if estimates)
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load(path):
    try:
        with open(os.path.join(DATA, path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save(path, obj):
    with open(os.path.join(DATA, path), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def derive(friday: date) -> bool:
    fri, sat, sun = friday, friday + timedelta(days=1), friday + timedelta(days=2)
    thu = friday - timedelta(days=1)
    f_fri, f_sat, f_sun = (load(f"daily/{d.isoformat()}.json") for d in (fri, sat, sun))
    if not (f_fri and f_sat and f_sun):
        print(f"  {friday}: missing Fri/Sat/Sun daily file — skipping.")
        return False
    if f_sun.get("is_estimates", False):
        print(f"  {friday}: Sunday daily is still an estimate — skipping.")
        return False

    wk_path = f"weekends/{friday.isoformat()}.json"
    wk = load(wk_path)
    if wk and not wk.get("is_estimates", False):
        print(f"  {friday}: weekend file already confirmed — leaving it alone.")
        return False

    f_thu = load(f"daily/{thu.isoformat()}.json") or {"chart": []}
    prev_fri = friday - timedelta(days=7)
    prev = load(f"weekends/{prev_fri.isoformat()}.json") or {"chart": []}
    prev_by = {norm(r["title"]): r for r in prev.get("chart", [])}

    def index(d):
        return {norm(r["title"]): r for r in d.get("chart", [])}

    I_fri, I_sat, I_sun, I_thu = index(f_fri), index(f_sat), index(f_sun), index(f_thu)
    old_rows = {norm(r["title"]): r for r in (wk or {}).get("chart", [])}

    keys = list(dict.fromkeys(list(old_rows.keys()) + list(I_sun.keys())))
    rows = []
    for k in keys:
        old = old_rows.get(k)
        sun_r = I_sun.get(k)
        gross = None
        # Primary: cumulative-total method. Sunday's cumulative total minus
        # Thursday's cumulative total is the film's full Fri-Sun take (this also
        # folds Thursday previews into the weekend, per industry convention).
        # A brand-new film with no Thursday row has Sunday's cumulative total as
        # its weekend gross. Fallback: sum of the three daily grosses.
        if sun_r and sun_r.get("total_gross"):
            if k in I_thu and I_thu[k].get("total_gross") is not None:
                gross = sun_r["total_gross"] - I_thu[k]["total_gross"]
            elif k not in prev_by and ((sun_r.get("days_in_release") or 99) <= 3 or (old and old.get("is_new"))):
                gross = sun_r["total_gross"]
        if gross is None and k in I_fri and k in I_sat and k in I_sun:
            gross = (I_fri[k].get("daily_gross") or 0) + (I_sat[k].get("daily_gross") or 0) + (I_sun[k].get("daily_gross") or 0)
        if gross is None:
            if old is None:
                continue
            row = dict(old)          # not on the daily charts — keep the estimate row
            rows.append(row)
            continue

        base = dict(old) if old else {
            "title": sun_r["title"],
            "movie_url": sun_r.get("movie_url", ""),
            "distributor": sun_r.get("distributor", ""),
            "is_new": False,
            "weeks_in_release": None,
            "last_rank": None,
        }
        if not base.get("distributor") and sun_r:
            base["distributor"] = sun_r.get("distributor", "")
        theaters = (sun_r or {}).get("theaters") or base.get("theaters") or 0
        total = (sun_r or {}).get("total_gross") or base.get("total_gross") or gross
        p = prev_by.get(k)
        base.update({
            "weekend_gross": int(gross),
            "theaters": theaters,
            "avg_per_theater": round(gross / theaters) if theaters else 0,
            "total_gross": total,
            "change_pct": round((gross / p["weekend_gross"] - 1) * 100, 1) if p and p.get("weekend_gross") else None,
            "theater_change": (theaters - p["theaters"]) if p and p.get("theaters") is not None else None,
        })
        rows.append(base)

    rows.sort(key=lambda r: -(r.get("weekend_gross") or 0))
    out_rows = []
    for i, r in enumerate(rows, 1):
        r.pop("rank", None)
        out_rows.append({"rank": i, **r})

    out = {
        "updated": datetime.now().isoformat(),
        "date_from": friday.isoformat(),
        "date_to": sun.isoformat(),
        "week_number": (wk or {}).get("week_number") or int(sun.strftime("%U")),
        "is_estimates": False,
        "chart": out_rows,
    }
    save(wk_path, out)

    # Keep the homepage "latest weekend" file in sync when this is the newest weekend.
    latest = load("weekend.json") or {}
    if (latest.get("date_from") or "") <= friday.isoformat():
        save("weekend.json", out)

    # Make sure the weekends index lists it.
    idx = load("weekends/index.json")
    if isinstance(idx, dict) and "dates" in idx and friday.isoformat() not in idx["dates"]:
        idx["dates"] = sorted(set(idx["dates"]) | {friday.isoformat()})
        save("weekends/index.json", idx)

    print(f"  {friday}: rebuilt weekend chart from daily actuals "
          f"({len(out_rows)} rows, #1 {out_rows[0]['title']} ${out_rows[0]['weekend_gross']:,}).")
    return True


def main():
    if len(sys.argv) > 1:
        derive(datetime.strptime(sys.argv[1], "%Y-%m-%d").date())
        return
    today = date.today()
    # Check the last few weekends; derive() skips anything not eligible.
    d = today - timedelta(days=(today.weekday() - 4) % 7)   # most recent Friday
    for back in range(0, 3):
        derive(d - timedelta(days=7 * back))


if __name__ == "__main__":
    main()
