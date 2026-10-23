// POST /api/auth/profile   Body (JSON): { display_name, location }
import { json, getUser, cleanName, isReserved } from "../../_lib/auth.js";

export async function onRequestPost({ request, env }) {
  const user = await getUser(request, env);
  if (!user) return json({ ok: false, error: "Not signed in." }, 401);
  let b;
  try { b = await request.json(); } catch (e) { return json({ ok: false, error: "Bad request." }, 400); }

  const name = cleanName(b.display_name);
  const loc = (b.location || "").toString().trim().slice(0, 100) || null;
  if (!name) return json({ ok: false, error: "Display name must be 2-30 characters (letters, numbers, spaces, . _ - ')." }, 400);
  if (name.toLowerCase() !== (user.display_name || "").toLowerCase() && isReserved(name)) {
    return json({ ok: false, error: "That display name is reserved." }, 409);
  }
  try {
    await env.DB.prepare("UPDATE users SET display_name = ?, display_name_lc = ?, location = ? WHERE id = ?")
      .bind(name, name.toLowerCase(), loc, user.id).run();
  } catch (e) {
    return json({ ok: false, error: "That display name is already taken." }, 409);
  }
  return json({ ok: true });
}
