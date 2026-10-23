// GET /api/auth/me -> { user: {...}|null, history: [...], spots_left }
import { json, getUser, getSetting, accountCount } from "../../_lib/auth.js";

export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ user: null });
  const user = await getUser(request, env);
  let spots = null;
  try {
    const cap = parseInt(await getSetting(env, "account_cap", "200"), 10) || 200;
    spots = Math.max(0, cap - (await accountCount(env)));
  } catch (e) {}
  if (!user) return json({ user: null, spots_left: spots });

  let history = [];
  try {
    const r = await env.DB.prepare(
      "SELECT weekend, player_name, picks_json FROM submissions WHERE user_id = ? ORDER BY weekend DESC LIMIT 100"
    ).bind(user.id).all();
    history = (r.results || []).map(x => ({ weekend: x.weekend, player_name: x.player_name, picks: JSON.parse(x.picks_json || "[]") }));
  } catch (e) {}
  return json({
    user: { display_name: user.display_name, email: user.email, location: user.location || "", role: user.role },
    history,
    spots_left: spots,
  });
}
