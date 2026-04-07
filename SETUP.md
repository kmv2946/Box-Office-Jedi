# Box Office Jedi — Setup Guide

## What We're Building

A static website hosted for free on Netlify, automatically updated daily via GitHub Actions.
No servers to manage, no monthly bills, no coding required after setup.

---

## One-Time Setup Steps

### Step 1 — Create a Free GitHub Account
GitHub is where your site's files live. It's free.

1. Go to https://github.com and sign up
2. Create a new repository called `boxofficejedi`
3. Set it to **Public**

### Step 2 — Get Your Free TMDB API Key
TMDB is The Movie Database — it powers the movie detail pages and all-time charts.

1. Go to https://www.themoviedb.org/signup and create a free account
2. Go to https://www.themoviedb.org/settings/api
3. Click "Create" → select "Developer" → fill out the short form
4. Copy your **API Key (v3 auth)** — it looks like a long string of letters and numbers

### Step 3 — Add Your TMDB Key to GitHub
This keeps your key secret while letting the automation use it.

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `TMDB_API_KEY`
4. Value: paste your TMDB key
5. Click **Add secret**

### Step 4 — Create a Free Netlify Account
Netlify hosts the site and handles the Derby form submissions.

1. Go to https://www.netlify.com and sign up (use your GitHub account to sign in — easiest)
2. Click **Add new site → Import an existing project**
3. Connect to GitHub and select your `boxofficejedi` repository
4. Leave all build settings blank (it's a static HTML site)
5. Click **Deploy site**

Your site will be live at a random URL like `amazing-jedi-123.netlify.com` within minutes.

### Step 5 — Connect Your Custom Domain
1. In Netlify, go to **Site settings → Domain management**
2. Click **Add custom domain**
3. Enter `boxofficejedi.com`
4. Netlify will show you two nameserver addresses (e.g. `dns1.p01.nsone.net`)
5. Log into GoDaddy → your domain → **Manage DNS → Nameservers**
6. Switch to **Custom nameservers** and paste Netlify's nameservers
7. Wait up to 24 hours for DNS to propagate (usually much faster)

HTTPS is automatic and free via Netlify.

---

## How the Automation Works

Every day at 9am ET, GitHub automatically:
1. Runs `scripts/scrape_the_numbers.py` → updates `data/daily.json`, `data/weekend.json`, `data/yearly.json`
2. Every Monday, runs `scripts/tmdb_api.py` → updates `data/alltime.json`, `data/movies/`, `data/now_playing.json`
3. Commits the new data files to the repo
4. Netlify detects the new commit and redeploys the site (takes ~30 seconds)

**If The Numbers is down or blocks the scraper:** The step is marked as `continue-on-error: true`, meaning the workflow finishes gracefully and yesterday's data stays on the site. You can manually copy fresh numbers from BOM or The Numbers and drop them into the JSON files yourself — we'll keep the format simple.

**To trigger an update manually:** Go to GitHub → Actions tab → "Update Box Office Data" → "Run workflow" button.

---

## Derby Game — How Submissions Work

1. Visitor fills out the Derby form and clicks Submit
2. Netlify captures the submission instantly (no server needed)
3. You get an email notification
4. All submissions visible at: Netlify dashboard → your site → **Forms → derby-game**
5. You can export submissions as CSV for scoring

Netlify free tier allows 100 form submissions/month. More than enough.

---

## File Structure

```
boxofficejedi/
├── index.html              ← Homepage
├── daily.html              ← Daily chart page
├── weekend.html            ← Weekend chart page
├── yearly.html             ← Year-to-date chart
├── alltime.html            ← All-time chart
├── derby.html              ← The Derby game form
├── forecast.html           ← Your weekly forecasts
├── news.html               ← Weekend roundup posts
├── releases.html           ← Release dates
├── showdowns.html          ← Movie comparisons
├── movie.html              ← Individual movie page template
├── data/
│   ├── daily.json          ← Auto-updated daily
│   ├── weekend.json        ← Auto-updated daily
│   ├── yearly.json         ← Auto-updated daily
│   ├── alltime.json        ← Auto-updated weekly (Mondays)
│   ├── now_playing.json    ← Auto-updated weekly (Derby dropdowns)
│   └── movies/
│       └── [tmdb_id].json  ← One file per movie
├── scripts/
│   ├── scrape_the_numbers.py
│   └── tmdb_api.py
├── .github/
│   └── workflows/
│       └── update-data.yml ← The automation
└── assets/
    ├── css/
    ├── fonts/
    └── images/
```
