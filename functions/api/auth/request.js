// POST /api/auth/request
// Body (JSON): { mode: "signup"|"login", email, name?, location?, agree?, "bot-field"? }
// Emails a one-time link. Nothing is created until the link is used.

import {
  json, sha256Hex, randomToken, nowSec, EMAIL_RE, cleanName,
  getSetting, accountCount, sendEmail, TOKEN_MINUTES,
} from "../../_lib/auth.js";

export async function onRequestPost({ request, env }) {
  if (!env.DB) return json({ ok: false, error: "Database not configured." }, 500);

  let b;
  try { b = await request.json(); } catch (e) { return json({ ok: false, error: "Bad request." }, 400); }

  if ((b["bot-field"] || "").toString().trim() !== "") return json({ ok: true }); // honeypot

  const mode = b.mode === "signup" ? "signup" : "login";
  const email = (b.email || "").toString().trim().toLowerCase();
  if (!EMAIL_RE.test(email) || email.length > 120) {
    return json({ ok: false, error: "Please enter a valid e-mail address." }, 400);
  }

  // Rate limits: 5 per email per hour, 20 per IP per hour.
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipKey = "ip:" + (await sha256Hex(ip + "|boxofficejedi"));
  const emKey = "email:" + (await sha256Hex(email));
  const since = nowSec() - 3600;
  try {
    const e1 = await env.DB.prepare("SELECT COUNT(*) AS n FROM auth_attempts WHERE k = ? AND created_at > ?").bind(emKey, since).first();
    const e2 = await env.DB.prepare("SELECT COUNT(*) AS n FROM auth_attempts WHERE k = ? AND created_at > ?").bind(ipKey, since).first();
    if ((e1 && e1.n >= 5) || (e2 && e2.n >= 20)) {
      return json({ ok: false, error: "Too many attempts. Please try again in an hour." }, 429);
    }
    await env.DB.batch([
      env.DB.prepare("INSERT INTO auth_attempts (k, created_at) VALUES (?, ?)").bind(emKey, nowSec()),
      env.DB.prepare("INSERT INTO auth_attempts (k, created_at) VALUES (?, ?)").bind(ipKey, nowSec()),
      env.DB.prepare("DELETE FROM auth_attempts WHERE created_at < ?").bind(nowSec() - 86400),
    ]);
  } catch (e) {
    return json({ ok: false, error: "Accounts are not set up yet." }, 500);
  }

  const existing = await env.DB.prepare("SELECT id, status FROM users WHERE email = ?").bind(email).first();

  let purpose = "login", name = null, loc = null;

  if (existing) {
    // Same response whether they hit "sign up" or "sign in": send a sign-in link.
    if (existing.status !== "active") return json({ ok: true });
  } else if (mode === "login") {
    // Don't reveal that no account exists.
    return json({ ok: true });
  } else {
    // New sign-up
    name = cleanName(b.name);
    loc = (b.location || "").toString().trim().slice(0, 100) || null;
    if (!name) return json({ ok: false, error: "Display name must be 2-30 characters (letters, numbers, spaces, . _ - ')." }, 400);
    if (!b.agree) return json({ ok: false, error: "You must confirm you are 13 or older and agree to the privacy policy." }, 400);

    if ((await getSetting(env, "signups_open", "1")) !== "1") {
      return json({ ok: false, error: "New sign-ups are closed right now." }, 403);
    }
    const cap = parseInt(await getSetting(env, "account_cap", "200"), 10) || 200;
    if ((await accountCount(env)) >= cap) {
      return json({ ok: false, full: true, error: "All " + cap + " founding accounts have been claimed. You can still play the Derby as a guest." }, 403);
    }
    const taken = await env.DB.prepare("SELECT 1 FROM users WHERE display_name_lc = ?").bind(name.toLowerCase()).first();
    if (taken) return json({ ok: false, error: "That display name is already taken." }, 409);
    purpose = "signup";
  }

  const token = randomToken(32);
  const hash = await sha256Hex(token);
  try {
    await env.DB.prepare(
      "INSERT INTO login_tokens (token_hash, email, purpose, display_name, location, expires_at) VALUES (?, ?, ?, ?, ?, ?)"
    ).bind(hash, email, purpose, name, loc, nowSec() + TOKEN_MINUTES * 60).run();

    const origin = new URL(request.url).origin;
    const link = origin + "/account.html?token=" + token;
    const text =
      "Box Office Jedi\n\n" +
      (purpose === "signup" ? "Welcome! Click the link below to finish creating your account:\n\n" : "Click the link below to sign in:\n\n") +
      link + "\n\n" +
      "This link works once and expires in " + TOKEN_MINUTES + " minutes. If you didn't ask for it, you can ignore this e-mail.\n";
    await sendEmail(env, email, purpose === "signup" ? "Finish creating your Box Office Jedi account" : "Your Box Office Jedi sign-in link", text);
  } catch (e) {
    return json({ ok: false, error: "Could not send the e-mail. Please try again shortly." }, 500);
  }
  return json({ ok: true });
}
