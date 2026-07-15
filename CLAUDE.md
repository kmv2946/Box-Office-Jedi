# Box Office Jedi — Handoff Notes for Claude

## Firm rules
- **NEVER use emojis on the site.** Anywhere. Not in HTML, not in prose, not in link callouts (we previously used a ▶ play button and Keaton had it stripped from every article). If you're tempted to reach for `&#x25B6;`, `★`, or any Unicode symbol as decoration — don't.
- **Never write speculative color commentary.** If you claim a specific number/player/film in a summary sentence, verify it against the actual data before writing it. Getting the leaderboard math right and then narrating "so-and-so won because of X" without checking is worse than no commentary at all.
- **Tell Keaton to `git fetch` before pushing** if the scraper may have run since his last pull (daily every day, weekend Sun/Mon, aggregate rebuilds on every push).

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
- `data/distributor_overrides.json` — studio mapping fallbacks. Add both bare-title (`furious`) and `the`-prefixed (`thefurious`) forms when the source scraper is inconsistent about the article.
- `data/daily_overrides.json` — patch missing/wrong daily entries. **Important**: this only applies on the NEXT scrape. If a daily file is already committed and pushed (e.g. Backrooms was missed on 6/15–6/17), the override alone won't fix the on-disk `data/daily/YYYY-MM-DD.json` — you also have to manually inject the row into that file (append to `chart[]`, re-sort by `daily_gross` desc, re-rank). Do BOTH so future re-scrapes keep the fix.

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

**Waiving the rank-13+ penalty:** on weeks where a film that placed in the top 10 wasn't offered as a Derby pick (e.g. BLEACH on 6/26, The Invite on 7/3, Furious/Stop That Train/BTS on 5/29), Keaton sometimes asks to waive the rank-13+ penalty so players aren't punished for picks that displaced into the lower chart. Add a `notes` field to the leaderboard JSON documenting this when it happens.

**Seeded/fake players:** Keaton periodically asks to round out a leaderboard to 10 with made-up entries (Nacho Libre from CA, Gru from Hollywoodland, supergirl, box office virgin, duck, etc.). He'll give the score directly. Add with `correct_ranks: 0` and whatever location he provides.

`correct_ranks` is a sidecar stat (how many picks landed at the right rank position); not used for scoring, only displayed. Word-overlap matching handles title variations between submissions and actuals. Roster has grown well past the launch cohort; the April 17 leaderboard is entirely seeded/fake names from the launch, and Mario LA + Dan Mack on May 22 are also seeded, but everything since May 29 is real submissions plus Keaton + occasional fill-in seeds.

## Yearly chart reissue filter (`scripts/build_yearly_chart.py`)
Three layered filters keep re-releases/restorations off the yearly charts:

1. **URL-paren year**: The Numbers gives reissues a fresh page with the original release year in parens, e.g. `/movie/Shrek-(2001)` or `/movie/Top-Gun-(1986)`. Any row whose `movie_url` ends in `-(YYYY)` where YYYY < chart year is dropped.
2. **Title-keyword**: drops rows whose title contains "re-release", "rerelease", "reissue", "restoration", "restored", "anniversary", "imax re-release", "remastered". Catches explicit reissues that share the chart year in their URL (e.g. "Hamilton 2025 Re-release", "Princess Mononoke 4K Restoration").
3. **Stealth-reissue**: catches reissues that share the original page's URL with no year suffix (e.g. TMNT II 2026 reuses `/movie/Teenage-Mutant-Ninja-Turtles-II-The-Secret-of-the-Ooze`). Signal: source's lifetime `total_gross` > 5× the in-year weekend sum AND `max_theaters` < 2000. A genuine current-year release has lifetime ≈ 1.1-1.3× yearly sum (lifetime adds weekday gross).

`total_gross` reported in the chart is `_running_sum` of in-year weekend grosses when the source's lifetime is more than 3× that sum (defensive — prevents reissue lifetime totals from leaking into the displayed gross). Otherwise uses `max(latest_total, running_sum)`.

To re-archive a past year after data corrections or filter tweaks: `python3 scripts/build_yearly_chart.py YYYY --archive` (writes `data/years/YYYY.json`). Current year auto-rebuilds via the `Build Yearly Chart` GitHub Action every Tuesday 9am ET.

## Recent shipped (May–July 2026)
Franchise foundation, Print + Inflation toggle on showdowns, polls D1 backend with Current/Past tabs, Kit newsletter migration, Top Stories expanded to 4 items with per-article `hide_from_home` opt-out, Smallest Drops 200-row chart, year-disambiguation across most data sources, scraper preview-filter with word-overlap matching, daily pct_change computed client-side, three-layer yearly reissue filter, per-title Derby scoring formalized with rank-13+ tail penalty (and per-week waiver mechanism), showdown.js override merge gated to prevent cross-year poster leaks, weekend daily scrape bumped from 2 PM ET to 3:30 PM ET Sat/Sun so The Numbers has time to post Friday-opener figures.

## Known bugs (structural, not yet fixed)
1. **Movie profile Domestic Total Gross is cut off at the release year.** `data/movie_totals.json` (which powers the movie page's total) is built from yearly chart files by `scripts/build_movie_totals_index.py`, which only see in-year weekend sums. Toy Story 2 shows $208M (1999-only) instead of $245M lifetime. The correct lifetime IS in the weekend shard's last row (`total_gross`) but the totals builder doesn't consult shards. Fix requires build_movie_totals_index.py to walk `data/movie_weekends_shards/*.json` and take `max(yearly_total, latest_shard_total)`.
2. **Weekend shards merge same-titled different-year films.** `scripts/aggregate_movie_weekends.py` keys entries by `norm_title(title)-year` when the movie_url has a `-(YYYY)` suffix, and falls back to bare `norm_title` when it doesn't. The Numbers gives ORIGINAL releases bare URLs (`/movie/Volcano`) and later remakes/reissues year-suffixed URLs (`/movie/Volcano-(2016)`), so 1997 Volcano and the 2016 "Volcano" (which is `/movie/Ixcanul`) both bucket to key `volcano`. Result: the volcano shard holds 29 weekends spanning 1997–2016, and clicking a "1997 Dec 2-4" weekend on the movie page links to Dec 2 2016. Fix: key entries by URL (with year derived from URL parens OR earliest weekend year), not by title. Regenerate all 27 letter shards. See prior chat "the long-term fix" for the full 5-piece change list before undertaking.

## Yearly chart redefinition (pending user upload)
Keaton wants the yearly chart's `total_gross` field to mean the **lifetime domestic gross** of films released that year, NOT the sum of in-year weekend grosses (which is what `build_yearly_chart.py` currently produces). He plans to upload manually-curated corrected charts. Don't automated-rebuild past `data/years/YYYY.json` files until that redefinition happens — leave the archived charts as-is when running `build_yearly_chart.py`.

## Ad rotation
Sidebar ad copy is hand-swapped across all HTML files on release date changes ("In Theaters June 12th" → "Now in Theaters" was a recent sitewide sed). If you swap ad artwork/copy, grep for the old string and update every file — the ad appears in every article page plus the homepage.

## Known pending
- CF deploy timeout issue — repo size
- Source PDF folders not yet gitignored
- Showdown.js shard lookup needs title-prefix fallback (bare slugs in SHOWDOWN_CONFIG don't resolve to year-suffixed shard keys without manual fix — override side was gated in June, shard side still needs work)

## User context
Keaton, sole creator, building for fun (not monetizing), targets the old BoxOfficeMojo community, wants it big + functional, throwback Web 1.0 aesthetic. Workspace folder: `/Users/keatonventura/Desktop/Box Office Jedi`.
