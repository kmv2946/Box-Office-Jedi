-- Box Office Jedi: accounts (migration 001)
-- Run once in the Cloudflare dashboard: Workers & Pages > D1 > (your DB) > Console.
-- Paste and run each statement. It is safe to run the CREATE statements twice
-- (IF NOT EXISTS); the two ALTER/INDEX lines at the bottom are not.

CREATE TABLE IF NOT EXISTS users (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  email           TEXT NOT NULL UNIQUE,          -- lowercase, verified by magic link
  display_name    TEXT NOT NULL,
  display_name_lc TEXT NOT NULL UNIQUE,          -- case-insensitive uniqueness
  location        TEXT,
  role            TEXT NOT NULL DEFAULT 'member',-- member | moderator | admin (for future forums)
  status          TEXT NOT NULL DEFAULT 'active',-- active | suspended
  created_at      INTEGER NOT NULL,
  last_login_at   INTEGER
);

-- One-time sign-in / sign-up links. Only a hash of the token is stored.
CREATE TABLE IF NOT EXISTS login_tokens (
  token_hash   TEXT PRIMARY KEY,
  email        TEXT NOT NULL,
  purpose      TEXT NOT NULL,                    -- signup | login
  display_name TEXT,                             -- signup only
  location     TEXT,                             -- signup only
  expires_at   INTEGER NOT NULL,
  used_at      INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
  id_hash    TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Simple rate limiting for sign-in requests.
CREATE TABLE IF NOT EXISTS auth_attempts (
  k          TEXT NOT NULL,                      -- "email:..." or "ip:..."
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_attempts ON auth_attempts(k, created_at);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('account_cap', '200');
INSERT OR IGNORE INTO settings (key, value) VALUES ('signups_open', '1');

-- Link derby submissions to accounts (guest submissions keep user_id NULL).
ALTER TABLE submissions ADD COLUMN user_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_user_weekend
  ON submissions(user_id, weekend) WHERE user_id IS NOT NULL;
