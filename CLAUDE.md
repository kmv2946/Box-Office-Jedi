# Box Office Jedi — Handoff Notes for Claude

## Stack & deploy
Pure static HTML/CSS/JS. **Cloudflare Pages** hosting, **Cloudflare Functions** for polls/Derby submit endpoints, **Cloudflare D1** (SQLite) for poll votes + Derby submissions. **Kit** (formerly ConvertKit) handles the newsletter on the $29/mo Standard plan, embedded via AJAX form on the homepage. **GitHub Actions** runs the daily/weekend scraper (Python) on schedule. Workflow: Claude edits files → user commits/pushes via **GitHub Desktop** → CF Pages auto-deploys. Tell user to `git fetch` before pushing if scrapers may have run.

## Auto-rebuilt files (do NOT hand-edit, they'll conflict)
A `rebuild-aggregates` GitHub Action regenerates these on every push: `distributors.json`, `movie_articles.json`, `daily.json`, `daily/index.json`, `weekends/index.json`. Edit the *source* files and let the workflow rebuild. Merge conflicts on these → mark resolved with the incoming branch and let the action rebuild.

## Slug & title conventions
- Slug format: `normtitle-year`, e.g. `backrooms-2026`, `it-2017`. `normKey()` strips to `[a-z0-9]`.
- Curly quotes in headlines for film titles: `&lsquo;Filmname&rsquo;` — closing curly quote doubles as possessive.
- Year disambiguation is essential — bare slugs like `martysupreme` will MISS the shard `martysupreme-2025` because shard lookups are exact-match (profile pages do prefix-fallback, showdowns don't yet — known gap).
- The scraper has word-overlap title canonicalization with **≥50% coverage required** (hardened to prevent generic-word collisions like "Project Hail Mary" vs "Untitled Jordan Peele Project").

## Override systems (these survive auto-rebuilds)
- `data/movie_meta_overrides.json` — poster_url, distributor, runtime for films TMDB hasn't enriched yet
- `data/distributor_overrides.json` — studio mapping fallbacks
- `data/daily_overrides.json` — patch missing/wrong daily entries

## Key data files
- `data/analysis.json` — editorial posts (forecasts, roundups). Prepend new entries, bump `updated` field.
- `data/predictions.json` — weekend predictions. Prepend new weekend block.
- `data/polls.json` — current/past polls with close dates.
- `data/releases.json` — release schedule. Sort within weekend by `theaters` desc. Home page widget + releases.html both pull from this.
- `data/derby/` — `games.json` (game list), `submissions-YYYY-MM-DD.csv`, `leaderboard-YYYY-MM-DD.json`.
- `data/franchises.json` — franchise definitions for franchise-chart.html

## Showdowns
Thin HTML shells with `window.SHOWDOWN_CONFIG = { title, breadcrumb, films: [{slug, title}] }`. `assets/js/showdown.js` renders. Has Print + Adjust-for-Inflation toolbar (reads `ticket_prices.json`, deep-clones films, recomputes grosses per release year). Index lives in `showdowns.html`.

## Derby
Players submit picks via `derby-predict.html` → CF Function writes to D1 → user exports CSV manually → Claude scores against actuals. **Scoring formula (per-title accuracy average, rank-agnostic):**
1. Use actuals rounded to 1 decimal place (millions) — matches how Keaton calculates by hand.
2. For each of a player's 10 picks: `accuracy = max(0, 1 − |pick − actual| / actual) × 100`, where `actual` is that film's actual weekend gross.
3. If the picked film placed at chart rank 11 or 12, still score normally against its actual gross — no penalty.
4. If it placed rank 13+, subtract 10 percentage points per rank past 12 (rank 13 = −10pp, rank 14 = −20pp, etc.), floored at 0.
5. If the picked film isn't on the weekend chart at all (no gross data), score = 0.
6. Player's score = mean of the 10 per-title accuracies, rounded to 2 decimals.

Keaton's own editorial predictions from `data/predictions.json` get included on the leaderboard as player_name `"Keaton"`, separate from any Derby form submissions. The CSV-form submission from `keatonventura@gmail.com` shows up under whatever name was typed in the form (e.g., "Rae Saunders") and is kept as its own row — don't merge it with Keaton.

`correct_ranks` is a sidecar stat (how many picks landed at the right rank position); not used for scoring, only displayed. Word-overlap matching handles title variations between submissions and actuals. **Current roster: 10 unique players, 17 submissions across 3 real weekends.** April 17 leaderboard is seeded/fake names from launch. Mario LA + Dan Mack on May 22 are also seeded.

## Recent shipped (May 2026)
Franchise foundation, Print + Inflation toggle on showdowns, polls D1 backend with Current/Past tabs, Kit newsletter migration, Top Stories expanded to 4 items, Smallest Drops 200-row chart, year-disambiguation across all data sources, scraper preview-filter with word-overlap matching, daily pct_change computed client-side.

## Known pending
- CF deploy timeout issue — repo size
- Source PDF folders not yet gitignored
- Showdown.js shard lookup needs title-prefix fallback (so bare slugs in SHOWDOWN_CONFIG resolve to year-suffixed shard keys without manual fix)

## User context
Keaton, sole creator, building for fun (not monetizing), targets the old BoxOfficeMojo community, wants it big + functional, throwback Web 1.0 aesthetic. Workspace folder: `/Users/keatonventura/Desktop/Box Office Jedi`.
