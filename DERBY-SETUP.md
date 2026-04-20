# Derby Game — Backend Setup (Cloudflare)

The derby submissions, averages, and leaderboard all run on **Cloudflare Pages Functions + D1** — free, native to your existing hosting, and scales on its own. You do this setup once; weekly maintenance is just editing `data/derby/games.json`.

## One-time setup

### 1. Install Wrangler (one-time)
On your Mac, in Terminal:
```sh
npm install -g wrangler
wrangler login
```
(Opens a browser, log in with the same account that hosts the Cloudflare Pages site.)

### 2. Create the D1 database
```sh
cd "Box Office Jedi"
wrangler d1 create boxofficejedi-derby
```
Wrangler prints a `database_id` — copy it.

### 3. Bind the database to your Pages project
Go to your Cloudflare dashboard → **Workers & Pages** → the Box Office Jedi project → **Settings → Functions → D1 database bindings** → **Add binding**:

- **Variable name:** `DB`
- **D1 database:** select `boxofficejedi-derby`
- Apply to **Production** and **Preview**.

### 4. Apply the schema
```sh
wrangler d1 execute boxofficejedi-derby --remote --file=./schema.sql
```
This creates the `submissions` table with indexes on weekend, IP hash, and email.

### 5. Push + deploy
Commit and push as usual. Cloudflare Pages picks up the `functions/` folder automatically and your endpoints go live:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/derby/submit`  | Accepts a submission, writes to D1 |
| `GET /api/derby/averages?weekend=YYYY-MM-DD` | Returns average predictions for that weekend |
| `GET /api/derby/check?weekend=YYYY-MM-DD`    | Returns `{submitted: true/false}` based on the visitor's IP |

## Weekly workflow

Every week you edit **one file only**: `data/derby/games.json`.

```jsonc
{
  "updated": "2026-04-19",
  "current_weekend": "2026-04-24",
  "games": [
    {
      "weekend":  "2026-04-24",
      "date_to":  "2026-04-26",
      "label":    "April 24–26",
      "label_long": "April 24–26, 2026",
      "status":   "open",             // "open" | "closed" | "actuals_posted"
      "submit_deadline": "2026-04-23T23:59:59-04:00",
      "headliner": "Michael",          // used by the homepage tagline
      "allowed_titles": ["..."],       // alphabetized list for the dropdown
      "leaderboard_url": null          // fill in after you score actuals
    }
  ]
}
```

When a new weekend opens, duplicate the most recent game entry at the top of the array, update the dates and `allowed_titles`, and set `current_weekend` to the new value.

## After Thursday night (deadline)

Nothing to do. The averages chart on `derby.html` calls `/api/derby/averages` and renders live from D1 submissions. Change `status` to `"closed"` in `games.json` if you want the submission form to hide itself; otherwise late submissions will still go through (and just won't be counted when you score).

## After weekend actuals

This is the one part that stays manual for now, because scoring logic can vary:

1. Pull submissions from D1:
   ```sh
   wrangler d1 execute boxofficejedi-derby --remote \
     --command="SELECT id, player_name, player_location, picks_json FROM submissions WHERE weekend = '2026-04-24'"
   ```
   Or use the Cloudflare dashboard D1 console to run the same query.
2. Score each submission against the actuals using whatever formula you want (weekend accuracy %, RMSE, etc.).
3. Write a JSON file at `data/derby/2026-04-24-leaderboard.json` with the top 10:
   ```json
   {
     "weekend": "2026-04-24",
     "updated": "2026-04-27",
     "leaderboard": [
       {"rank": 1, "player_name": "Keaton", "location": "NYC", "score": 96.84},
       ...
     ]
   }
   ```
4. Set `leaderboard_url` in `games.json` to `"data/derby/2026-04-24-leaderboard.json"`.
5. Set `status: "actuals_posted"`.

`derby-leaderboard.html` picks it up automatically.

(If you later want to automate scoring too, a `functions/api/derby/score.js` endpoint could read your weekend actuals from `data/weekends/<date>.json` and compute/store the scores. For now, manual keeps you in control.)

## Cost

All of this runs inside Cloudflare's **free tier** forever (for anything close to this site's expected traffic):

- **Pages Functions:** 100,000 requests/day free
- **D1:** 5 GB storage, 5 million row reads/day, 100 K row writes/day — free
- **Bandwidth / static files:** unlimited on Pages

If the site ever blows up and you cross the free tier, Cloudflare's Workers Paid plan is a flat **$5/month** and covers 10× the free limits. No per-submission fees.

## Why this architecture

- **One stack.** Site, forms, APIs, and database all live in Cloudflare. You never touch a second vendor.
- **Self-contained.** The whole backend is in two folders you already commit: `functions/` and `data/`.
- **Fast.** D1 queries run at the Cloudflare edge; each endpoint returns in tens of milliseconds.
- **Durable.** Submissions are durable rows in SQLite, not form emails you have to remember to export.
- **Migratable.** If you ever want to move to something else, export with `wrangler d1 export` — everything's just SQL.
