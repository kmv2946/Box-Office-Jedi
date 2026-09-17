#!/usr/bin/env python3
"""
Box Office Jedi — Rebuild all weekend-shard-derived all-time charts
=====================================================================
Companion to build_alltime_chart.py (which handles domestic-lifetime).
This script rebuilds every OTHER data/charts/*.json file that can be
correctly computed from data/movie_weekends_shards/*.json (opening
weekends, monthly/holiday weekend records, Nth-weekend records, second-
weekend drops, per-theater averages, widest releases, movies that never
hit #1) plus, cross-referencing data/movies_meta_shards/*.json for MPA
rating and worldwide revenue, the MPA-rating and worldwide-gross charts.

Deliberately NOT included here (left static — see report printed at the
end): any chart needing single-day precision (fastest-to-$X-million,
top single/opening days, Friday share of opening weekend, Christmas
single-day grosses, Thanksgiving 5-day). data/movie_daily_shards/ only
covers the site's own daily scraper archive (a few months of 2026 as of
this writing), nowhere near enough history to support genuine "all-time"
claims — rebuilding those charts from it would misrepresent recent
releases as record holders they are not. They stay static until the
daily archive has real historical depth.

Design: each chart keeps its EXISTING columns/label/category/slug
(read from the current static file) so alltime-chart.html's column-role
detection keeps working unchanged. Only `rows`, `updated`, and `source`
are recomputed. Row values are produced as a name->string dict per
film and mapped onto each chart's own column order by lowercased
column name, so column-order differences between charts (there are
several) don't need to be hardcoded per chart.

Known inherited limitations (same as build_alltime_chart.py):
  - Weekend-shard title collisions (CLAUDE.md Known Bug #2) for
    non-year-suffixed titles.
  - Distributor/MPA lookups key on normalized TITLE TEXT ONLY (no
    year), so a remake sharing its original's title could inherit the
    wrong distributor/rating in rare cases.
  - MPA rating coverage is ~64% and worldwide revenue coverage is
    ~58% of data/movies_meta_shards (TMDB enrichment backlog) — films
    missing that data are simply excluded from the MPA/worldwide
    charts, not guessed.

Usage:
    python3 scripts/build_alltime_weekend_charts.py
"""
import json
import glob
import os
import re
import calendar
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKEND_SHARDS_DIR = os.path.join(REPO_ROOT, "data", "movie_weekends_shards")
META_SHARDS_DIR = os.path.join(REPO_ROOT, "data", "movies_meta_shards")
DISTRIBUTORS_PATH = os.path.join(REPO_ROOT, "data", "distributors.json")
CHARTS_DIR = os.path.join(REPO_ROOT, "data", "charts")
INDEX_PATH = os.path.join(CHARTS_DIR, "index.json")

WIDE_THEATER_THRESHOLD = 600  # "wide release" cutoff for per-theater-average-wide

REISSUE_TITLE_PHRASES = (
    "re-release", "rerelease", "re release",
    "reissue",
    "restoration", "4k restoration", "restored",
    "anniversary",
    "imax re-release",
    "(re-release)",
    "remastered",
)

# Charts intentionally left static — see module docstring.
SKIP_SLUGS = {
    "domestic-lifetime",  # handled by build_alltime_chart.py
    "days-single-days",
    "days-opening-days",
    "friday-share-of-opening-weekend",
    "top-holiday-single-day-grosses-christmas",
    "weekends-thanksgiving-5-day",
    "misc-fastest-to-100-million",
    "misc-fastest-to-200-million",
    "misc-fastest-to-300-million",
    "misc-fastest-to-400-million",
    "misc-fastest-to-500-million",
    "misc-fastest-to-600-million",
    "misc-fastest-to-700-million",
}

MONTH_SLUGS = {
    "weekends-january": 1, "weekends-february": 2, "weekends-march": 3,
    "weekends-april": 4, "weekends-may": 5, "weekends-june": 6,
    "weekends-july": 7, "weekends-august": 8, "weekends-september": 9,
    "weekends-october": 10, "weekends-november": 11, "weekends-december": 12,
}

NTH_WEEKEND_SLUGS = {
    "weekends-second-weekends": 2, "weekends-third-weekends": 3,
    "weekends-fourth-weekends": 4, "weekends-fifth-weekends": 5,
    "weekends-sixth-weekends": 6, "weekends-seventh-weekends": 7,
}

MPA_SLUGS = {
    "top-lifetime-grosses-by-mpa-rating-g": ("G",),
    "top-lifetime-grosses-by-mpa-rating-pg": ("PG",),
    "top-lifetime-grosses-by-mpa-rating-g-and-pg": ("G", "PG"),
    "top-lifetime-grosses-by-mpa-rating-pg-13": ("PG-13",),
    "top-lifetime-grosses-by-mpa-rating-r": ("R",),
}


# ── formatting helpers ──────────────────────────────────────────────
def fmt_dollars(n):
    return "$" + "{:,}".format(int(round(n)))


def fmt_int(n):
    return "{:,}".format(int(n))


def fmt_pct(x):
    return "{:.1f}%".format(x)


def fmt_signed_pct(x):
    sign = "+" if x >= 0 else ""
    return "{}{:.1f}%".format(sign, x)


def parse_date(dstr):
    try:
        return datetime.strptime(dstr, "%Y-%m-%d").date()
    except Exception:
        return None


def fmt_date_single(dstr):
    d = parse_date(dstr)
    if not d:
        return dstr or ""
    return "{} {}, {}".format(d.strftime("%b"), d.day, d.year)


def fmt_date_range3(dstr):
    d = parse_date(dstr)
    if not d:
        return dstr or ""
    end = d + timedelta(days=2)
    if d.month == end.month:
        return "{} {}-{}, {}".format(d.strftime("%b"), d.day, end.day, end.year)
    return "{} {}-{} {}, {}".format(d.strftime("%b"), d.day, end.strftime("%b"), end.day, end.year)


def norm_key(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def is_reissue_title(title):
    if not title:
        return False
    low = title.lower()
    return any(p in low for p in REISSUE_TITLE_PHRASES)


# ── holiday-window helpers ──────────────────────────────────────────
def last_monday_of_may(year):
    c = calendar.Calendar()
    mondays = [d for d in c.itermonthdates(year, 5) if d.month == 5 and d.weekday() == 0]
    return mondays[-1]


def fourth_thursday_of_november(year):
    c = calendar.Calendar()
    thursdays = [d for d in c.itermonthdates(year, 11) if d.month == 11 and d.weekday() == 3]
    return thursdays[3]


def is_memorial_day_weekend(d):
    anchor_friday = last_monday_of_may(d.year) - timedelta(days=3)
    return d == anchor_friday


def is_fourth_of_july_weekend(d):
    anchor = datetime(d.year, 7, 4).date()
    return abs((d - anchor).days) <= 3 and d.weekday() == 4  # Friday within a week of July 4


def is_thanksgiving_3day_weekend(d):
    anchor_friday = fourth_thursday_of_november(d.year) + timedelta(days=1)
    return d == anchor_friday


HOLIDAY_SLUGS = {
    "weekends-memorial-day": is_memorial_day_weekend,
    "weekends-fourth-of-july": is_fourth_of_july_weekend,
    "weekends-thanksgiving-3-day": is_thanksgiving_3day_weekend,
}


# ── load source data ────────────────────────────────────────────────
def load_distributor_lookup():
    try:
        with open(DISTRIBUTORS_PATH, encoding="utf-8") as f:
            return json.load(f).get("by_title", {})
    except Exception:
        return {}


def load_meta_lookup():
    """key (with or without -year) -> {mpaa, revenue}"""
    lookup = {}
    for path in glob.glob(os.path.join(META_SHARDS_DIR, "*.json")):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for key, rec in (d.get("entries") or {}).items():
            lookup[key] = {
                "mpaa": (rec.get("mpaa") or "").strip(),
                "revenue": rec.get("revenue") or 0,
            }
    return lookup


def meta_for(title, year, meta_lookup):
    nk = norm_key(title)
    if year and f"{nk}-{year}" in meta_lookup:
        return meta_lookup[f"{nk}-{year}"]
    if nk in meta_lookup:
        return meta_lookup[nk]
    return {"mpaa": "", "revenue": 0}


def load_films():
    """Same universe/filtering as build_alltime_chart.py's domestic-lifetime,
    extended to carry full weekend history + distributor + mpaa."""
    distributor_lookup = load_distributor_lookup()
    meta_lookup = load_meta_lookup()

    raw = []
    for path in sorted(glob.glob(os.path.join(WEEKEND_SHARDS_DIR, "*.json"))):
        try:
            shard = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for key, rec in (shard.get("entries") or {}).items():
            title = (rec.get("title") or "").strip()
            if not title or is_reissue_title(title):
                continue
            weekends = rec.get("weekends") or []
            if not weekends:
                continue
            weekends = sorted(weekends, key=lambda w: w.get("n") or 0)
            lifetime = max((w.get("total_gross") or 0) for w in weekends)
            if lifetime <= 0:
                continue
            ranks = [w["rank"] for w in weekends if w.get("rank")]
            raw.append({
                "title": title,
                "year": rec.get("year"),
                "movie_url": rec.get("movie_url") or "",
                "weekends": weekends,
                "lifetime": lifetime,
                "best_rank": min(ranks) if ranks else None,
                "distributor": distributor_lookup.get(norm_key(title), ""),
                "mpaa": meta_for(title, rec.get("year"), meta_lookup)["mpaa"],
                "revenue": meta_for(title, rec.get("year"), meta_lookup)["revenue"],
            })

    best = {}
    for m in raw:
        dk = (m["title"], m["year"])
        if dk not in best or m["lifetime"] > best[dk]["lifetime"]:
            best[dk] = m
    films = list(best.values())

    # Overall rank on the flagship all-time domestic list — used by
    # "never hit #1" and the MPA-rating charts' "Overall Rank" column.
    ranked = sorted(films, key=lambda m: -m["lifetime"])
    overall_rank = {(m["title"], m["year"]): i + 1 for i, m in enumerate(ranked)}
    for m in films:
        m["overall_rank"] = overall_rank[(m["title"], m["year"])]

    return films


# ── row-field builders (name -> string) ─────────────────────────────
def base_fields(m, gross, ref_date, theaters, distributor=None):
    avg = (gross / theaters) if theaters else 0
    pct_of_total = (gross / m["lifetime"] * 100) if m["lifetime"] else 0
    return {
        "release": m["title"],
        "title": m["title"],
        "title (click to view)": m["title"],
        "gross": fmt_dollars(gross),
        "opening": fmt_dollars(gross),
        "2nd weekend": fmt_dollars(gross),
        "total gross": fmt_dollars(m["lifetime"]),
        "lifetime gross": fmt_dollars(m["lifetime"]),
        "% of total": fmt_pct(pct_of_total),
        "% of weekend": fmt_pct(pct_of_total),
        "theaters": fmt_int(theaters) if theaters else "",
        "max theaters": fmt_int(theaters) if theaters else "",
        "average": fmt_dollars(avg) if theaters else "",
        "date": fmt_date_single(ref_date) if ref_date else "",
        "wide date": fmt_date_single(ref_date) if ref_date else "",
        "friday date": fmt_date_single(ref_date) if ref_date else "",
        "distributor": distributor if distributor is not None else m["distributor"],
        "studio": distributor if distributor is not None else m["distributor"],
        "year": str(m["year"]) if m["year"] else "",
    }


def map_row(columns, fields, rank):
    fields = dict(fields)
    fields["rank"] = str(rank)
    return [fields.get(c.lower().strip(), "") for c in columns]


def write_chart(slug, columns, label, category, rows, source_note):
    payload = {
        "slug": slug,
        "label": label,
        "category": category,
        "source": source_note,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "columns": columns,
        "rows": rows,
    }
    out_path = os.path.join(CHARTS_DIR, f"{slug}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return len(rows)


# ── chart builders ───────────────────────────────────────────────────
def build_openings(films, meta, top_n):
    rows = []
    ranked = sorted(films, key=lambda m: -m["weekends"][0]["gross"])[:top_n]
    for i, m in enumerate(ranked, 1):
        open_wk = m["weekends"][0]
        fields = base_fields(m, open_wk["gross"], open_wk["date"], open_wk.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_month(films, meta, month, top_n):
    cand = [m for m in films if parse_date(m["weekends"][0]["date"]) and parse_date(m["weekends"][0]["date"]).month == month]
    ranked = sorted(cand, key=lambda m: -m["weekends"][0]["gross"])[:top_n]
    rows = []
    for i, m in enumerate(ranked, 1):
        open_wk = m["weekends"][0]
        fields = base_fields(m, open_wk["gross"], open_wk["date"], open_wk.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_holiday(films, meta, check_fn, top_n):
    cand = []
    for m in films:
        best = None
        for w in m["weekends"]:
            d = parse_date(w["date"])
            if d and check_fn(d):
                if best is None or w["gross"] > best["gross"]:
                    best = w
        if best:
            cand.append((m, best))
    cand.sort(key=lambda t: -t[1]["gross"])
    cand = cand[:top_n]
    rows = []
    for i, (m, w) in enumerate(cand, 1):
        fields = base_fields(m, w["gross"], w["date"], w.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_nth_weekend(films, meta, n, top_n):
    cand = [(m, m["weekends"][n - 1]) for m in films if len(m["weekends"]) >= n]
    cand.sort(key=lambda t: -t[1]["gross"])
    cand = cand[:top_n]
    rows = []
    for i, (m, w) in enumerate(cand, 1):
        fields = base_fields(m, w["gross"], w["date"], w.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_second_weekend_drops(films, meta, top_n, smallest=False, min_theaters=None):
    cand = []
    for m in films:
        if len(m["weekends"]) < 2:
            continue
        w1, w2 = m["weekends"][0], m["weekends"][1]
        if not w1["gross"]:
            continue
        if min_theaters and (w1.get("theaters") or 0) < min_theaters:
            continue
        pct = (w2["gross"] - w1["gross"]) / w1["gross"] * 100
        cand.append((m, w1, w2, pct))
    cand.sort(key=lambda t: -t[3] if smallest else t[3])
    cand = cand[:top_n]
    rows = []
    for i, (m, w1, w2, pct) in enumerate(cand, 1):
        fields = base_fields(m, w1["gross"], m["weekends"][0]["date"], w1.get("theaters") or 0)
        fields["opening"] = fmt_dollars(w1["gross"])
        fields["2nd weekend"] = fmt_dollars(w2["gross"])
        fields["% change"] = fmt_signed_pct(pct)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_per_theater_avg(films, meta, top_n, wide=False):
    cand = []
    for m in films:
        best = None
        for w in m["weekends"]:
            th = w.get("theaters") or 0
            if th <= 0:
                continue
            if wide and th < WIDE_THEATER_THRESHOLD:
                continue
            avg = w["gross"] / th
            if best is None or avg > best[1]:
                best = (w, avg)
        if best:
            cand.append((m, best[0], best[1]))
    cand.sort(key=lambda t: -t[2])
    cand = cand[:top_n]
    rows = []
    for i, (m, w, avg) in enumerate(cand, 1):
        fields = base_fields(m, w["gross"], w["date"], w.get("theaters") or 0)
        fields["date"] = fmt_date_range3(w["date"])
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_widest(films, meta, top_n, opening_only=False):
    cand = []
    for m in films:
        if opening_only:
            w = m["weekends"][0]
            cand.append((m, w))
        else:
            w = max(m["weekends"], key=lambda w: w.get("theaters") or 0)
            cand.append((m, w))
    cand.sort(key=lambda t: -(t[1].get("theaters") or 0))
    cand = cand[:top_n]
    rows = []
    for i, (m, w) in enumerate(cand, 1):
        fields = base_fields(m, w["gross"], w["date"], w.get("theaters") or 0)
        fields["date"] = fmt_date_range3(w["date"])
        fields["max theaters"] = fmt_int(w.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_never_hit_1(films, meta, top_n):
    cand = [m for m in films if m["best_rank"] and m["best_rank"] != 1]
    cand.sort(key=lambda m: -m["lifetime"])
    cand = cand[:top_n]
    rows = []
    for i, m in enumerate(cand, 1):
        fields = base_fields(m, m["lifetime"], m["weekends"][0]["date"], 0)
        fields["top rank"] = str(m["best_rank"])
        fields["overall rank"] = str(m["overall_rank"])
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_r_rated(films, meta, top_n):
    cand = [m for m in films if m["mpaa"] == "R"]
    ranked = sorted(cand, key=lambda m: -m["weekends"][0]["gross"])[:top_n]
    rows = []
    for i, m in enumerate(ranked, 1):
        open_wk = m["weekends"][0]
        fields = base_fields(m, open_wk["gross"], open_wk["date"], open_wk.get("theaters") or 0)
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_mpa(films, meta, ratings, top_n):
    cand = [m for m in films if m["mpaa"] in ratings]
    cand.sort(key=lambda m: -m["lifetime"])
    cand = cand[:top_n]
    rows = []
    for i, m in enumerate(cand, 1):
        fields = base_fields(m, m["lifetime"], m["weekends"][0]["date"], 0)
        fields["rank"] = str(i)
        fields["overall rank"] = str(m["overall_rank"])
        rows.append(map_row(meta["columns"], fields, i))
    return rows


def build_worldwide(films, meta, top_n):
    cand = []
    skipped_inconsistent = 0
    for m in films:
        wgross = m.get("revenue") or 0
        dgross = m["lifetime"]
        if wgross <= 0 or dgross <= 0:
            continue
        if wgross < dgross:
            skipped_inconsistent += 1
            continue
        cand.append((m, wgross, dgross))
    cand.sort(key=lambda t: -t[1])
    cand = cand[:top_n]
    rows = []
    for i, (m, wgross, dgross) in enumerate(cand, 1):
        fgross = wgross - dgross
        fields = {
            "rank": str(i),
            "title": m["title"],
            "release": m["title"],
            "worldwide lifetime gross": fmt_dollars(wgross),
            "domestic lifetime gross": fmt_dollars(dgross),
            "domestic %": fmt_pct(dgross / wgross * 100),
            "foreign lifetime gross": fmt_dollars(fgross),
            "foreign %": fmt_pct(fgross / wgross * 100),
            "year": str(m["year"]) if m["year"] else "",
        }
        rows.append([fields.get(c.lower().strip(), "") for c in meta["columns"]])
    return rows, skipped_inconsistent


# ── main ─────────────────────────────────────────────────────────────
def main():
    films = load_films()
    print(f"Loaded {len(films)} films from weekend shards.")

    try:
        idx = json.load(open(INDEX_PATH, encoding="utf-8"))
    except Exception:
        idx = {"updated": "", "charts": []}
    idx_by_slug = {c["slug"]: c for c in idx.get("charts", [])}

    built = []
    skipped_static = []

    for slug in sorted(glob.glob(os.path.join(CHARTS_DIR, "*.json"))):
        pass  # placeholder, real loop below uses index entries

    for entry in idx.get("charts", []):
        slug = entry["slug"]
        if slug in SKIP_SLUGS:
            skipped_static.append(slug)
            continue
        chart_path = os.path.join(CHARTS_DIR, f"{slug}.json")
        try:
            existing = json.load(open(chart_path, encoding="utf-8"))
        except Exception:
            print(f"  ! could not read existing {slug}.json, skipping")
            continue
        columns = existing.get("columns") or []
        label = existing.get("label") or entry.get("label", slug)
        category = existing.get("category") or entry.get("category", "")
        meta = {"columns": columns}
        top_n = max(len(existing.get("rows") or []), 1)

        source_note = "movie-weekends-shards-aggregate"
        skipped_note = ""

        if slug == "weekends-openings":
            rows = build_openings(films, meta, top_n)
        elif slug in MONTH_SLUGS:
            rows = build_month(films, meta, MONTH_SLUGS[slug], top_n)
        elif slug in HOLIDAY_SLUGS:
            rows = build_holiday(films, meta, HOLIDAY_SLUGS[slug], top_n)
        elif slug in NTH_WEEKEND_SLUGS:
            rows = build_nth_weekend(films, meta, NTH_WEEKEND_SLUGS[slug], top_n)
        elif slug == "weekend-biggest-second-weekend-drops":
            rows = build_second_weekend_drops(films, meta, top_n, smallest=False)
        elif slug == "smallest-second-weekend-drops-wide-2000-plus":
            rows = build_second_weekend_drops(films, meta, top_n, smallest=True, min_theaters=2000)
        elif slug == "top-per-theater-average-limited-and-wide-release":
            rows = build_per_theater_avg(films, meta, top_n, wide=False)
        elif slug == "top-per-theater-averages-wide-release":
            rows = build_per_theater_avg(films, meta, top_n, wide=True)
        elif slug == "widest-releases-opening":
            rows = build_widest(films, meta, top_n, opening_only=True)
        elif slug == "widest-releases-overall":
            rows = build_widest(films, meta, top_n, opening_only=False)
        elif slug == "grosses-movies-that-never-hit-1":
            rows = build_never_hit_1(films, meta, top_n)
        elif slug == "weekends-r-rated":
            # Existing static file had a malformed/broken column schema
            # (swapped Release/Rank order, two blank trailing headers).
            # Rebuilding with the standard weekends-openings schema.
            columns = ["Rank", "Release", "Gross", "Total Gross", "% of Total",
                       "Theaters", "Average", "Date", "Distributor"]
            meta = {"columns": columns}
            rows = build_r_rated(films, meta, top_n)
            source_note = "movie-weekends-shards-aggregate + movies-meta-shards (mpaa)"
        elif slug in MPA_SLUGS:
            rows = build_mpa(films, meta, MPA_SLUGS[slug], top_n)
            source_note = "movie-weekends-shards-aggregate + movies-meta-shards (mpaa)"
        elif slug == "top-lifetime-grosses-worldwide":
            rows, skipped = build_worldwide(films, meta, top_n)
            source_note = "movie-weekends-shards-aggregate + movies-meta-shards (revenue)"
            if skipped:
                skipped_note = f" ({skipped} films skipped: worldwide < domestic, likely incomplete TMDB revenue data)"
        else:
            print(f"  ? no builder for {slug}, leaving static")
            skipped_static.append(slug)
            continue

        n = write_chart(slug, columns, label, category, rows, source_note)
        built.append((slug, n, skipped_note))

        entry["rows"] = n
        entry["updated"] = datetime.now().strftime("%b %d, %Y")

    idx["updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)

    print(f"\nBuilt {len(built)} live charts:")
    for slug, n, note in built:
        print(f"  {slug}: {n} rows{note}")
    print(f"\nLeft static ({len(skipped_static)}): {', '.join(skipped_static)}")


if __name__ == "__main__":
    main()
