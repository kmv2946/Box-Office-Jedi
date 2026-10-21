// POST /api/auth/logout
import { json, getCookie, SESSION_COOKIE, sha256Hex, sessionCookie } from "../../_lib/auth.js";

export async function onRequestPost({ request, env }) {
  const tok = getCookie(request, SESSION_COOKIE);
  if (tok && env.DB && /^[a-f0-9]{64}$/.test(tok)) {
    try {
      await env.DB.prepare("DELETE FROM sessions WHERE id_hash = ?").bind(await sha256Hex(tok)).run();
    } catch (e) {}
  }
  return json({ ok: true }, 200, { "Set-Cookie": sessionCookie("", 0) });
}
