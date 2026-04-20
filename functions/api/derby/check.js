// GET /api/derby/check?weekend=YYYY-MM-DD
// ---------------------------------------
// Returns { submitted: true/false } based on whether this visitor's IP has
// already submitted for the given weekend. Used by the main derby page to
// show "Your predictions are already counted" if the visitor comes back.
//
// This is best-effort (shared IPs, VPNs, mobile carriers all muddy the waters),
// so the client also uses localStorage as the primary signal. This endpoint
// is a secondary check.

async function sha256Hex(str) {
  const data = new TextEncoder().encode(str);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

export async function onRequestGet({ request, env }) {
  if (!env.DB) return Response.json({ submitted: false });
  const weekend = (new URL(request.url).searchParams.get("weekend") || "").trim();
  if (!weekend) return Response.json({ submitted: false });

  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (!ip) return Response.json({ submitted: false });
  const ipHash = await sha256Hex(ip + "|" + weekend + "|boxofficejedi");

  try {
    const row = await env.DB.prepare(
      "SELECT 1 FROM submissions WHERE weekend = ? AND ip_hash = ? LIMIT 1"
    ).bind(weekend, ipHash).first();
    return Response.json({ submitted: !!row });
  } catch (e) {
    return Response.json({ submitted: false });
  }
}
