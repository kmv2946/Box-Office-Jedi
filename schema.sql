-- Box Office Jedi — D1 schema
-- ===========================
-- Apply once when setting up the Cloudflare Pages project:
--
--   wrangler d1 execute boxofficejedi-derby --remote --file=./schema.sql
--
-- (See DERBY-SETUP.md for full setup instructions.)

CREATE TABLE IF NOT EXISTS submissions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  weekend         TEXT    NOT NULL,          -- e.g. "2026-04-24"
  player_name     TEXT    NOT NULL,
  player_email    TEXT    NOT NULL,
  player_location TEXT,
  player_comments TEXT,
  picks_json      TEXT    NOT NULL,          -- JSON: [{rank, title, gross}, ...]
  ip_hash         TEXT,                      -- sha256(ip + '|' + weekend + '|boxofficejedi')
  user_agent      TEXT,
  created_at      INTEGER NOT NULL            -- unix seconds
);

CREATE INDEX IF NOT EXISTS idx_submissions_weekend         ON submissions(weekend);
CREATE INDEX IF NOT EXISTS idx_submissions_weekend_ip      ON submissions(weekend, ip_hash);
CREATE INDEX IF NOT EXISTS idx_submissions_weekend_email   ON submissions(weekend, player_email);
