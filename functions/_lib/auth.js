// Shared helpers for account endpoints. Not a route (no onRequest export).

export const SESSION_COOKIE = "boj_session";
export const SESSION_DAYS = 30;
export const TOKEN_MINUTES = 20;

export async function sha256Hex(str) {
  const data = new TextEncoder().encode(str);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

export function randomToken(bytes = 32) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return [...a].map(b => b.toString(16).padStart(2, "0")).join("");
}

export function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...headers },
  });
}

export const nowSec = () => Math.floor(Date.now() / 1000);

export function getCookie(request, name) {
  const c = request.headers.get("Cookie") || "";
  for (const part of c.split(/;\s*/)) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i) === name) return part.slice(i + 1);
  }
  return null;
}

export function sessionCookie(value, maxAgeSec) {
  return `${SESSION_COOKIE}=${value}; Path=/; Max-Age=${maxAgeSec}; HttpOnly; Secure; SameSite=Lax`;
}

// Returns the signed-in user row (id, email, display_name, location, role) or null.
export async function getUser(request, env) {
  if (!env.DB) return null;
  const tok = getCookie(request, SESSION_COOKIE);
  if (!tok || !/^[a-f0-9]{64}$/.test(tok)) return null;
  const h = await sha256Hex(tok);
  try {
    return await env.DB.prepare(
      `SELECT u.id, u.email, u.display_name, u.location, u.role
         FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.id_hash = ? AND s.expires_at > ? AND u.status = 'active'`
    ).bind(h, nowSec()).first();
  } catch (e) {
    return null;
  }
}

export async function createSession(env, userId) {
  const tok = randomToken(32);
  const h = await sha256Hex(tok);
  const t = nowSec();
  const exp = t + SESSION_DAYS * 86400;
  await env.DB.prepare(
    "INSERT INTO sessions (id_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(h, userId, t, exp).run();
  return { cookie: sessionCookie(tok, SESSION_DAYS * 86400) };
}

export async function getSetting(env, key, fallback) {
  try {
    const r = await env.DB.prepare("SELECT value FROM settings WHERE key = ?").bind(key).first();
    return r ? r.value : fallback;
  } catch (e) {
    return fallback;
  }
}

export async function accountCount(env) {
  const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first();
  return r ? r.n : 0;
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Display names: 2-30 chars, letters/numbers/space and . _ - ' only.
export function cleanName(s) {
  s = (s || "").toString().replace(/\s+/g, " ").trim();
  if (s.length < 2 || s.length > 30) return null;
  if (!/^[\p{L}\p{N} ._'’-]+$/u.test(s)) return null;
  return s;
}

// Names nobody can register (they'd look like official / editorial accounts).
const RESERVED = ["keaton", "admin", "administrator", "moderator", "mod", "staff", "jedi",
  "boxofficejedi", "box office jedi", "official", "support", "system"];
export function isReserved(name) {
  const n = (name || "").toLowerCase().replace(/\s+/g, " ").trim();
  return RESERVED.includes(n) || RESERVED.includes(n.replace(/[^a-z0-9]/g, ""));
}

export async function sendEmail(env, to, subject, text) {
  if (!env.RESEND_API_KEY) throw new Error("RESEND_API_KEY not set");
  const from = env.MAIL_FROM || "Box Office Jedi <login@boxofficejedi.com>";
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: "Bearer " + env.RESEND_API_KEY },
    body: JSON.stringify({ from, to: [to], subject, text }),
  });
  if (!r.ok) throw new Error("Resend error " + r.status + ": " + (await r.text()).slice(0, 200));
}
