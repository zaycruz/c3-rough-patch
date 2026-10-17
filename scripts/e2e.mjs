#!/usr/bin/env node
// E2E check: hits every endpoint of a deployed C3 Worker, checks the contract, saves everything under runs/.
// Usage: node scripts/e2e.mjs [baseUrl]   (default: the workers.dev deploy)
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = (process.argv[2] || "https://c3-rough-patch.zay-259.workers.dev").replace(/\/$/, "");
const checks = [];
const responses = {};
const check = (name, ok, info) => { checks.push({ name, ok: !!ok, ...(info ? { info } : {}) }); };

async function get(path) {
  const t0 = Date.now();
  const res = await fetch(BASE + path);
  const text = await res.text();
  let body = text;
  try { body = JSON.parse(text); } catch {}
  return { status: res.status, ms: Date.now() - t0, headers: Object.fromEntries(res.headers), body };
}

const STATUSES = ["alert", "watch", "ok"];

// GET /
const home = await get("/");
check("GET / returns 200 HTML", home.status === 200 && /<title>Bad Week Radar<\/title>/.test(home.body));
responses["/"] = { status: home.status, ms: home.ms, bytes: home.body.length };

// GET /api/c3/survivors
const roster = await get("/api/c3/survivors");
responses["/api/c3/survivors"] = roster;
const list = Array.isArray(roster.body) ? roster.body : [];
check("roster 200 and non-empty array", roster.status === 200 && list.length > 0, { count: list.length });
check("roster CORS header", roster.headers["access-control-allow-origin"] === "*");
const keys = ["survivorId", "displayName", "status", "headline", "updatedAt"];
check("roster tiles have exactly the contract keys", list.every((r) => JSON.stringify(Object.keys(r).sort()) === JSON.stringify([...keys].sort())));
check("roster ids are c3-prefixed", list.every((r) => /^c3-P\d{5}$/.test(r.survivorId)));
check("roster status in ok|watch|alert", list.every((r) => STATUSES.includes(r.status)));
check("roster sorted alert > watch > ok", list.every((r, i) => i === 0 || STATUSES.indexOf(list[i - 1].status) <= STATUSES.indexOf(r.status)));
const mix = Object.fromEntries(STATUSES.map((s) => [s, list.filter((r) => r.status === s).length]));
check("roster has at least one alert", mix.alert > 0, mix);

// GET /api/c3/survivors/:id for every survivor
let detailOk = 0, demoHits = 0, flagged = 0;
const failures = [];
for (const r of list) {
  const d = await get(`/api/c3/survivors/${r.survivorId}`);
  const b = d.body;
  const n = b?.charts?.dates?.length;
  const ok = d.status === 200 && b.survivorId === r.survivorId && b.status === r.status && b.headline === r.headline &&
    typeof b.summary === "string" && Array.isArray(b.evidence) && b.evidence.length > 0 &&
    Array.isArray(b.recommendations) && b.recommendations.length > 0 && b.charts && n > 0 &&
    ["risk", "steps", "restingHeartRate", "hrv", "sleepHours", "doseDays"].every((k) => Array.isArray(b.charts[k]) && b.charts[k].length === n) &&
    !("demo" in b);
  if (ok) detailOk++; else failures.push(r.survivorId);
  if (r === list[0]) responses[`/api/c3/survivors/${r.survivorId}`] = d;
  const demo = await get(`/api/c3/survivors/${r.survivorId}?demo=1`);
  if (r.status !== "ok") { flagged++; if (demo.body?.demo?.roughPatchStartsInDays) demoHits++; }
  if (r === list[0]) responses[`/api/c3/survivors/${r.survivorId}?demo=1`] = { status: demo.status, demo: demo.body?.demo };
}
check("every survivor panel matches the contract (and hides demo outcome)", detailOk === list.length, { ok: detailOk, failures });
check("flagged survivors whose rough patch did start within 14 days (informational)", true, { flagged, startedWithin14d: demoHits });

const missing = await get("/api/c3/survivors/c3-nope");
check("unknown survivor returns 404 JSON", missing.status === 404 && missing.body?.error);
responses["/api/c3/survivors/c3-nope"] = missing;

// GET /api/c3/metrics
const met = await get("/api/c3/metrics");
responses["/api/c3/metrics"] = met;
const M = met.body?.methods || {};
check("metrics 200 with model and baselines", met.status === 200 && M.model && M.schedule && M.steps_rule);
if (M.model && M.schedule && M.steps_rule) {
  const sum = (k) => ({ weekAuc: M[k].weeks.auc, weekPrecision: M[k].weeks.precision, weekRecall: M[k].weeks.recall,
    episodeRecall: M[k].episodes.episode_recall, erRecall: M[k].episodes.er_recall, medianLeadDays: M[k].episodes.median_lead_days,
    alertPrecision: M[k].episodes.alert_precision, alertsPerPatientMonth: M[k].episodes.alerts_per_patient_month });
  const s = { steps_rule: sum("steps_rule"), schedule: sum("schedule"), model: sum("model") };
  check("model beats both baselines on week AUC and episode recall",
    s.model.weekAuc > s.schedule.weekAuc && s.model.weekAuc > s.steps_rule.weekAuc &&
    s.model.episodeRecall > s.schedule.episodeRecall && s.model.episodeRecall > s.steps_rule.episodeRecall, s);
  check("median lead time >= 2 days", s.model.medianLeadDays >= 2, { medianLeadDays: s.model.medianLeadDays });
}

const passed = checks.every((c) => c.ok);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const out = { base: BASE, ranAt: new Date().toISOString(), passed, checks, responses };
mkdirSync("runs", { recursive: true });
writeFileSync(`runs/e2e-${stamp}.json`, JSON.stringify(out, null, 2));
writeFileSync("runs/e2e-latest.json", JSON.stringify(out, null, 2));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}${c.info ? "  " + JSON.stringify(c.info) : ""}`);
console.log(`\n${passed ? "ALL PASSED" : "FAILED"}  -> runs/e2e-${stamp}.json`);
process.exit(passed ? 0 : 1);
