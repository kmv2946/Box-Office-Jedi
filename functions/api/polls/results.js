// GET /api/polls/results
// ----------------------
// Returns vote counts merged from data/polls.json baseline + live D1 votes.
// Query params:
//   ?poll_id=2026-summer-top-grosser  → results for one poll
//   (none)                             → results for ALL polls
//
// Response shape:
//   { ok:true, polls: { "<poll_id>": { "<option_id>": votes, ... }, ... } }

async function fetchPollsJson(request) {
  const url = new URL("/data/polls.json", request.url);
  const r = await fetch(url.toString(), { cf: { cacheTtl: 30 } });
  if (!r.ok) throw new Error("polls.json fetch failed");
  return await r.json();
}

export async function onRequestGet({ request, env }) {
  if (!env.DB) {
    return new Response(JSON.stringify({ ok: false, error: "DB not configured" }),
      { status: 500, headers: { "content-type": "application/json" } });
  }

  let data;
  try {
    data = await fetchPollsJson(request);
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: "polls.json fetch failed" }),
      { status: 500, headers: { "content-type": "application/json" } });
  }
  const polls = data.polls || [];

  const url = new URL(request.url);
  const onePoll = url.searchParams.get("poll_id");
  const targets = onePoll ? polls.filter(p => p.id === onePoll) : polls;

  const out = {};
  for (const p of targets) {
    const merged = {};
    (p.options || []).forEach(o => { merged[o.id] = o.votes || 0; });
    try {
      const { results } = await env.DB.prepare(
        "SELECT option_id, COUNT(*) AS n FROM poll_votes WHERE poll_id = ? GROUP BY option_id"
      ).bind(p.id).all();
      (results || []).forEach(r => {
        merged[r.option_id] = (merged[r.option_id] || 0) + Number(r.n);
      });
    } catch (e) {
      // table might not exist yet — baseline alone is fine
    }
    out[p.id] = merged;
  }

  return new Response(JSON.stringify({ ok: true, polls: out }), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=15",  // tiny cache; results refresh frequently
    },
  });
}
