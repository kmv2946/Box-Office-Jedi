#!/usr/bin/env python3
"""
Box Office Jedi — Movie Articles Index Builder
================================================
Walks every article listed in `data/analysis.json` and `data/features.json`,
parses the HTML for `movie.html?...` links, and produces:

    data/movie_articles.json
    {
      "updated": "...",
      "by_slug":  { "michael-2026": [{title, href, kind, date}, ...] },
      "by_title": { "michael":      [{title, href, kind, date}, ...] }
    }

The movie profile page (`movie.html`) reads this map to render the
"Related Articles" panel automatically — no more hand-curating per-film
lists. Articles get cross-referenced via every film they mention.

Slug rule: when a link includes `&year=YYYY`, we key it as `title-YYYY`
(matching the rest of the slug system). Plain title links land in
`by_title` only.

Run:
    python3 scripts/build_movie_articles_index.py
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime
from urllib.parse import unquote


DATA_DIR = "data"


def norm_title(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# Pull every <a href="movie.html?..."> link out of an article's HTML.
# Captures the full href so we can read both `title=` and `year=` params.
LINK_RE = re.compile(
    r'<a [^>]*href="(movie\.html\?[^"#]*)"[^>]*>',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r'[?&]title=([^&]+)', re.IGNORECASE)
YEAR_RE  = re.compile(r'[?&]year=(\d{4})', re.IGNORECASE)
SLUG_RE  = re.compile(r'[?&]slug=([^&]+)', re.IGNORECASE)


def extract_film_keys(article_path):
    """Return the set of (slug, title_key) pairs an article links to.
    Each pair represents one film mention. Used to cross-reference."""
    try:
        with open(article_path) as f:
            html = f.read()
    except FileNotFoundError:
        return []

    pairs = []
    seen = set()
    for m in LINK_RE.finditer(html):
        # HTML-decode the href so &amp;year=2026 → &year=2026 and the
        # year/title/slug regexes below match. Without this, year suffixes
        # written as HTML entities (the default when authoring HTML) are
        # silently dropped and the link gets indexed by bare title only.
        import html as _html
        href = _html.unescape(m.group(1))
        slug_m = SLUG_RE.search(href)
        title_m = TITLE_RE.search(href)
        year_m = YEAR_RE.search(href)
        slug = unquote(slug_m.group(1)) if slug_m else ''
        title = unquote(title_m.group(1)) if title_m else ''
        year = year_m.group(1) if year_m else ''
        title_key = norm_title(title)
        # If the link explicitly includes ?slug=, that wins.
        # Otherwise, build a slug from title + year if both are present.
        if slug:
            slug_key = norm_title(slug.replace('-', ' ')) if '-' not in slug else slug
            # If the explicit slug was already a slug-form like "michael-2026", keep it.
            slug_key = slug if '-' in slug else slug_key
        elif title_key and year:
            slug_key = f"{title_key}-{year}"
        else:
            slug_key = ''
        # Dedupe within a single article
        key = (slug_key, title_key)
        if key in seen:
            continue
        seen.add(key)
        pairs.append({'slug_key': slug_key, 'title_key': title_key, 'title': title})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # Pull every article from analysis.json + features.json
    articles = []
    for src in ('analysis.json', 'features.json'):
        d = load_json(os.path.join(DATA_DIR, src))
        if d and isinstance(d.get('articles'), list):
            articles.extend(d['articles'])

    by_slug = {}
    by_title = {}
    scanned = 0
    skipped = 0
    for a in articles:
        url = (a.get('url') or '').strip()
        title = a.get('title') or ''
        kind  = a.get('type') or ''
        date  = a.get('date') or ''
        if not url or not title:
            skipped += 1
            continue
        # The article URL is relative to the repo root (e.g. forecast-may-1-2026.html)
        article_path = url.lstrip('/')
        if not os.path.exists(article_path):
            skipped += 1
            continue
        scanned += 1
        entry = {
            'title': title,
            'href':  url,
            'kind':  kind.title() if kind else '',
            'date':  date,
        }
        for pair in extract_film_keys(article_path):
            sk = pair['slug_key']
            tk = pair['title_key']
            if sk:
                by_slug.setdefault(sk, []).append(entry)
            if tk:
                by_title.setdefault(tk, []).append(entry)

    # Within each list, keep articles sorted newest-first and dedupe by href
    def dedupe_sort(lst):
        seen = set()
        out = []
        for e in sorted(lst, key=lambda x: x.get('date', ''), reverse=True):
            h = e['href']
            if h in seen:
                continue
            seen.add(h)
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

    out_path = os.path.join(DATA_DIR, 'movie_articles.json')
    print(f"  Scanned {scanned} articles ({skipped} skipped).")
    print(f"  Indexed mentions for {len(by_slug)} slug keys + {len(by_title)} title keys.")
    if args.dry_run:
        # Show a few sample lookups
        for sample in ('michael-2026', 'thedevilwearsprada', 'thesupermariogalaxymovie-2026'):
            v = by_slug.get(sample) or by_title.get(sample)
            if v:
                print(f"    {sample:35s} → {len(v)} article(s)")
                for e in v[:3]:
                    print(f"        - [{e['kind']}] {e['title']}")
        print("  (dry run — no file written)")
        return
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Wrote {out_path}")


if __name__ == '__main__':
    main()
