// POST /api/polls/vote
// --------------------
// Records one poll vote. Form fields (multipart or urlencoded):
//   poll_id    e.g. "2026-summer-top-grosser"
//   option_id  e.g. "spider-man-brand-new-day"
//
// Dedup: one vote per (poll_id, ip_hash). Repeat submission returns
// { ok:true, duplicate:true } and DOES NOT increment.
//
// Response: { ok:true, results: [{option_id, votes}, ...] } — counts include
//           the simulated baseline from data/polls.json + live votes from D1.

async function sha256Hex(str) {
  const data = new TextEncoder().encode(str);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function bad(msg, status = 400) {
  return new Response(JSON.stringify({ ok: false, error: msg }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function fetchPollsJson(request) {
  // Read the canonical polls.json from the same origin so we can:
  //  - validate poll_id and option_id against the published list
  //  - reject votes for closed polls (closes < today)
  //  - return baseline+real merged counts
  const url = new URL("/data/polls.json", request.url);
  const r = await fetch(url.toString(), { cf: { cacheTtl: 30 } });
  if (!r.ok) throw new Error("polls.json fetch failed");
  return await r.json();
}

function pollIsClosed(poll) {
  if (!poll || !poll.closes) return false;
  const [y, m, d] = String(poll.closes).split("-").map(Number);
  // closes is "last day still open" (so 2026-05-01 means valid through end of May 1)
  const closeEnd = new Date(Date.UTC(y, (m || 1) - 1, d || 1, 23, 59, 59));
  return Date.now() > closeEnd.getTime();
}

async function getMergedResults(db, polls, pollId) {
  const poll = (polls || []).find(p => p.id === pollId);
  if (!poll) return null;
  const baseline = {};
  (poll.options || []).forEach(o => { baseline[o.id] = o.votes || 0; });
  // Add live counts from D1 on top of the baseline
  let live = {};
  try {
    const { results } = await db.prepare(
      "SELECT option_id, COUNT(*) AS n FROM poll_votes WHERE poll_id = ? GROUP BY option_id"
    ).bind(pollId).all();
    (results || []).forEach(r => { live[r.option_id] = (live[r.option_id] || 0) + Number(r.n); });
  } catch (e) {
    // table may not exist yet — return baseline alone
    live = {};
  }
  return (poll.options || []).map(o => ({
    option_id: o.id,
    votes:     (baseline[o.id] || 0) + (live[o.id] || 0),
  }));
}

export async function onRequestPost({ request, env }) {
  if (!env.DB) return bad("Database not configured (env.DB missing).", 500);

  // Parse body — accept form-encoded or JSON
  let pollId = "", optionId = "";
  const ct = (request.headers.get("content-type") || "").toLowerCase();
  try {
    if (ct.includes("application/json")) {
      const body = await request.json();
      pollId   = String(body.poll_id || "").trim();
      optionId = String(body.option_id || "").trim();
    } else {
      const form = await request.formData();
      pollId   = String(form.get("poll_id") || "").trim();
      optionId = String(form.get("option_id") || "").trim();
    }
  } catch (e) {
    return bad("Could not parse body.");
  }

  if (!pollId)   return bad("Missing poll_id.");
  if (!optionId) return bad("Missing option_id.");

  // Validate against polls.json
  let polls;
  try {
    const data = await fetchPollsJson(request);
    polls = data.polls || [];
  } catch (e) {
    return bad("Could not load poll definitions.", 500);
  }
  const poll = polls.find(p => p.id === pollId);
  if (!poll) return bad("Unknown poll.");
  if (!(poll.options || []).some(o => o.id === optionId)) {
    return bad("Unknown option for this poll.");
  }
  if (pollIsClosed(poll)) {
    return bad("Voting is closed for this poll.", 403);
  }

  // Dedup by IP + poll
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = ip ? await sha256Hex(ip + "|" + pollId + "|boxofficejedi") : null;
  const ua = (request.headers.get("User-Agent") || "").slice(0, 200);
  const db = env.DB;

  // Check for an existing vote from this IP for this poll
  let existing = null;
  try {
    existing = await db.prepare(
      "SELECT id FROM poll_votes WHERE poll_id = ? AND ip_hash = ? LIMIT 1"
    ).bind(pollId, ipHash).first();
  } catch (e) {
    // table might not exist yet — INSERT below will surface it
  }

  if (existing) {
    const merged = await getMergedResults(db, polls, pollId);
    return new Response(JSON.stringify({
      ok: true, duplicate: true, results: merged,
    }), { headers: { "content-type": "application/json" } });
  }

  try {
    await db.prepare(
      "INSERT INTO poll_votes (poll_id, option_id, ip_hash, user_agent, created_at) VALUES (?, ?, ?, ?, ?)"
    ).bind(pollId, optionId, ipHash, ua, Math.floor(Date.now() / 1000)).run();
  } catch (e) {
    return bad("Could not save vote: " + (e.message || e), 500);
  }

  const merged = await getMergedResults(db, polls, pollId);
  return new Response(JSON.stringify({ ok: true, results: merged }), {
    headers: { "content-type": "application/json" },
  });
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    },
  });
}
