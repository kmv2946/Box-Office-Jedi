// GET /api/derby/averages?weekend=YYYY-MM-DD
// ------------------------------------------
// Returns the average-of-all-entries picks for a given weekend, grouped by
// the movie title that appeared somewhere in any submission's top 10.
//
// Response shape:
//   {
//     weekend:     "2026-04-24",
//     submissions: 255,
//     averages: [
//       { rank: 1, title: "The Super Mario Galaxy Movie", avg_pred: 28.4, votes: 247 },
//       { rank: 2, title: "Lee Cronin's The Mummy",       avg_pred: 17.2, votes: 198 },
//       ...
//     ]
//   }
//
// The "avg_pred" is the arithmetic mean of predicted grosses (in millions)
// across every submission that included that title. "votes" shows how
// many submissions even picked that film. The list is sorted by avg_pred
// descending and truncated to the top 10.

function bad(msg, status = 400) {
  return new Response(JSON.stringify({ ok: false, error: msg }), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function onRequestGet({ request, env }) {
  if (!env.DB) return bad("Database not configured.", 500);

  const url = new URL(request.url);
  const weekend = (url.searchParams.get("weekend") || "").trim();
  if (!weekend) return bad("Missing ?weekend=YYYY-MM-DD");

  const db = env.DB;
  let countRow, rows;
  try {
    countRow = await db.prepare(
      "SELECT COUNT(*) AS n FROM submissions WHERE weekend = ?"
    ).bind(weekend).first();
    rows = await db.prepare(
      "SELECT picks_json FROM submissions WHERE weekend = ?"
    ).bind(weekend).all();
  } catch (e) {
    return bad("Query failed: " + (e.message || e), 500);
  }

  const submissions = (countRow && countRow.n) || 0;
  if (submissions === 0) {
    return new Response(JSON.stringify({ weekend, submissions: 0, averages: [] }), {
      headers: { "content-type": "application/json", "cache-control": "public, max-age=60" },
    });
  }

  // Aggregate: title -> { total_gross, votes }
  const agg = new Map();
  for (const r of rows.results || []) {
    let picks;
    try { picks = JSON.parse(r.picks_json); } catch (e) { continue; }
    if (!Array.isArray(picks)) continue;
    for (const p of picks) {
      if (!p || !p.title) continue;
      const cur = agg.get(p.title) || { total: 0, votes: 0 };
      cur.total += (typeof p.gross === "number" ? p.gross : parseFloat(p.gross) || 0);
      cur.votes += 1;
      agg.set(p.title, cur);
    }
  }

  const averages = [...agg.entries()].map(([title, v]) => ({
    title,
    avg_pred: Math.round((v.total / v.votes) * 10) / 10,
    votes:    v.votes,
  }));
  averages.sort((a, b) => b.avg_pred - a.avg_pred);
  const top = averages.slice(0, 10).map((x, i) => Object.assign({ rank: i + 1 }, x));

  return new Response(JSON.stringify({
    weekend,
    submissions,
    averages: top,
  }), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=60", // 1-minute edge cache
    },
  });
}
