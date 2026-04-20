// POST /api/derby/submit
// -----------------------
// Accepts a single derby submission and writes it to the D1 database.
// Enforces one entry per (weekend, ip_hash) and one per (weekend, email).
//
// Expected form fields (multipart/form-data or application/x-www-form-urlencoded):
//   weekend            e.g. "2026-04-24"
//   player_name        required
//   player_email       required
//   player_location    optional
//   player_comments    optional
//   pick_1_title ... pick_10_title
//   pick_1_gross ... pick_10_gross    (as strings like "24.7")
//   bot-field          honeypot; must be empty
//
// Response: JSON { ok: true } on success, or { ok: false, error: "..." }.

// Quick SHA-256 helper — Cloudflare Workers runtime has SubtleCrypto.
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

export async function onRequestPost({ request, env }) {
  if (!env.DB) {
    return bad("Database not configured (env.DB missing).", 500);
  }

  // Parse the form body
  let form;
  try {
    form = await request.formData();
  } catch (e) {
    return bad("Could not parse form data.");
  }

  // Honeypot
  if ((form.get("bot-field") || "").trim() !== "") {
    return new Response(JSON.stringify({ ok: true }), { // silently drop
      headers: { "content-type": "application/json" },
    });
  }

  const weekend      = (form.get("weekend") || "").toString().trim();
  const playerName   = (form.get("player_name") || "").toString().trim();
  const playerEmail  = (form.get("player_email") || "").toString().trim().toLowerCase();
  const playerLoc    = (form.get("player_location") || "").toString().trim();
  const playerNotes  = (form.get("player_comments") || "").toString().trim();

  if (!weekend)                                return bad("Missing weekend.");
  if (!playerName)                             return bad("Missing name.");
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(playerEmail)) return bad("Invalid e-mail.");
  if (playerName.length > 80 || playerLoc.length > 100 || playerNotes.length > 1000) {
    return bad("One of the fields is too long.");
  }

  // Collect picks
  const picks = [];
  const seenTitles = new Set();
  for (let i = 1; i <= 10; i++) {
    const title = (form.get(`pick_${i}_title`) || "").toString().trim();
    const grossStr = (form.get(`pick_${i}_gross`) || "").toString().trim();
    if (!title || !grossStr) return bad(`Pick ${i} is incomplete.`);
    if (seenTitles.has(title)) return bad(`Pick ${i}: "${title}" was selected more than once.`);
    seenTitles.add(title);
    const gross = parseFloat(grossStr);
    if (!isFinite(gross) || gross < 0 || gross > 1000) {
      return bad(`Pick ${i}: "${grossStr}" is not a valid gross in millions.`);
    }
    picks.push({ rank: i, title, gross });
  }

  // Rate-limit / dedup — hash the IP+weekend so we store a non-identifying marker.
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = ip ? await sha256Hex(ip + "|" + weekend + "|boxofficejedi") : null;
  const ua = (request.headers.get("User-Agent") || "").slice(0, 200);

  const db = env.DB;

  // Check for an existing submission from this IP or email for this weekend.
  try {
    const existing = await db.prepare(
      "SELECT id FROM submissions WHERE weekend = ? AND (ip_hash = ? OR player_email = ?) LIMIT 1"
    ).bind(weekend, ipHash, playerEmail).first();
    if (existing) {
      return new Response(JSON.stringify({
        ok: false,
        error: "You’ve already submitted picks for this weekend.",
        duplicate: true,
      }), { status: 409, headers: { "content-type": "application/json" } });
    }
  } catch (e) {
    // Fall through — table may not yet exist; the INSERT below will surface it.
  }

  // Insert
  try {
    await db.prepare(
      `INSERT INTO submissions
         (weekend, player_name, player_email, player_location, player_comments,
          picks_json, ip_hash, user_agent, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      weekend, playerName, playerEmail, playerLoc || null, playerNotes || null,
      JSON.stringify(picks), ipHash, ua, Math.floor(Date.now() / 1000)
    ).run();
  } catch (e) {
    return bad("Could not save submission: " + (e.message || e), 500);
  }

  return new Response(JSON.stringify({ ok: true, weekend }), {
    headers: { "content-type": "application/json" },
  });
}

// OPTIONS for CORS preflight (in case it's ever called cross-origin)
export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    },
  });
}
