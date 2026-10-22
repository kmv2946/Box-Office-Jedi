// POST /api/auth/verify   Body (JSON): { token }
// Consumes a one-time link, creates the account if it's a sign-up, claims the
// player's past Derby entries (matched by verified e-mail), and sets the session cookie.

import {
  json, sha256Hex, nowSec, getSetting, accountCount, createSession,
} from "../../_lib/auth.js";

export async function onRequestPost({ request, env }) {
  if (!env.DB) return json({ ok: false, error: "Database not configured." }, 500);
  let b;
  try { b = await request.json(); } catch (e) { return json({ ok: false, error: "Bad request." }, 400); }
  const token = (b.token || "").toString();
  if (!/^[a-f0-9]{64}$/.test(token)) return json({ ok: false, error: "This link is not valid." }, 400);

  const hash = await sha256Hex(token);
  const row = await env.DB.prepare("SELECT * FROM login_tokens WHERE token_hash = ?").bind(hash).first();
  if (!row || row.used_at || row.expires_at < nowSec()) {
    return json({ ok: false, error: "This link has expired or was already used. Please request a new one." }, 400);
  }

  // Burn the token first (only one request can win the race).
  const burn = await env.DB.prepare("UPDATE login_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL")
    .bind(nowSec(), hash).run();
  if (!burn.meta || burn.meta.changes !== 1) {
    return json({ ok: false, error: "This link was already used." }, 400);
  }

  let user = await env.DB.prepare("SELECT id, status FROM users WHERE email = ?").bind(row.email).first();
  let created = false;

  if (!user) {
    if (row.purpose !== "signup") return json({ ok: false, error: "No account found." }, 400);
    const cap = parseInt(await getSetting(env, "account_cap", "200"), 10) || 200;
    if ((await accountCount(env)) >= cap) {
      return json({ ok: false, full: true, error: "All founding accounts have been claimed." }, 403);
    }
    try {
      await env.DB.prepare(
        `INSERT INTO users (email, display_name, display_name_lc, location, created_at, last_login_at)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).bind(row.email, row.display_name, row.display_name.toLowerCase(), row.location, nowSec(), nowSec()).run();
    } catch (e) {
      return json({ ok: false, error: "That display name was just taken. Please sign up again with another." }, 409);
    }
    user = await env.DB.prepare("SELECT id, status FROM users WHERE email = ?").bind(row.email).first();
    created = true;
  }
  if (user.status !== "active") return json({ ok: false, error: "This account is not active." }, 403);

  await env.DB.prepare("UPDATE users SET last_login_at = ? WHERE id = ?").bind(nowSec(), user.id).run();

  // Claim past guest entries made with this (now verified) e-mail.
  let claimed = 0;
  try {
    const res = await env.DB.prepare(
      `UPDATE submissions SET user_id = ?
        WHERE user_id IS NULL AND lower(player_email) = ?
          AND weekend NOT IN (SELECT weekend FROM submissions WHERE user_id = ?)`
    ).bind(user.id, row.email, user.id).run();
    claimed = (res.meta && res.meta.changes) || 0;
  } catch (e) { /* non-fatal */ }

  const { cookie } = await createSession(env, user.id);
  return json({ ok: true, created, claimed, newsletter: created && row.newsletter === 1, email: row.email }, 200, { "Set-Cookie": cookie });
}
