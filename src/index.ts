/**
 * C3 Bad Week Radar API (Coach Console module).
 *   GET /api/c3/survivors       roster tiles in priority order: urgent (by ER risk), then review-today (red-flag diary note),
 *                               then alert > watch > ok, then by risk. Precomputed: served as the static asset
 *                               public/api/c3/survivors (see public/_headers); this route is the same data as a fallback
 *   GET /api/c3/survivors/:id   survivor panel: status, evidence, recommendations, chart series
 *   GET /api/c3/metrics         held-out evaluation: headline (with CIs), model vs baselines, fairness by group
 *   GET /                       standalone demo page (public/index.html)
 * Scores are computed offline (analysis/train.py, analysis/export.py) and baked into src/data.
 */
import S from "./data/survivors.json";
import M from "./data/metrics.json";

interface Env {
  ASSETS: { fetch(req: Request): Promise<Response> };
}

type Detail = (typeof S.details)[keyof typeof S.details];
const details = S.details as Record<string, Detail>;

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "content-type",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=60", ...CORS },
  });

/** The coach view never sees the demo-only outcome unless the demo page asks for it. */
function panel(d: Detail, withOutcome: boolean) {
  if (withOutcome) return d;
  const { demo: _demo, ...rest } = d;
  return rest;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (!path.startsWith("/api/")) return env.ASSETS.fetch(req);
    if (req.method !== "GET") return json({ error: "method not allowed" }, 405);

    if (path === "/api/c3/survivors") {
      return json(S.roster.map(({ survivorId, displayName, status, headline, updatedAt, urgent, tier, priority, risk, urgentRisk, reviewToday }) =>
        ({ survivorId, displayName, status, headline, updatedAt, urgent, tier, priority, risk, urgentRisk, reviewToday })));
    }
    const m = path.match(/^\/api\/c3\/survivors\/([^/]+)$/);
    if (m) {
      const d = details[decodeURIComponent(m[1])];
      return d ? json(panel(d, url.searchParams.get("demo") === "1")) : json({ error: "survivor not found" }, 404);
    }
    if (path === "/api/c3/metrics") return json({ asOf: S.asOf, ...M });
    return json({ error: "not found" }, 404);
  },
};
