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
const keys = ["survivorId", "displayName", "status", "headline", "updatedAt", "urgent", "tier", "priority", "risk", "urgentRisk"];
check("roster tiles have exactly the contract keys", list.every((r) => JSON.stringify(Object.keys(r).sort()) === JSON.stringify([...keys].sort())));
check("roster ids are c3-prefixed", list.every((r) => /^c3-P\d{5}$/.test(r.survivorId)));
check("roster status in ok|watch|alert", list.every((r) => STATUSES.includes(r.status)));
const rank = (r) => (r.urgent ? -1 : STATUSES.indexOf(r.status));
check("roster sorted urgent > alert > watch > ok", list.every((r, i) => i === 0 || rank(list[i - 1]) <= rank(r)));
check("urgent survivors are always status alert", list.every((r) => !r.urgent || r.status === "alert"));
check("tier and priority are first-class: tier = urgent|alert|watch|ok, priority = 1..n in list order",
  list.every((r, i) => r.priority === i + 1 && r.tier === (r.urgent ? "urgent" : r.status) && typeof r.urgentRisk === "number"));
const mix = Object.fromEntries(STATUSES.map((s) => [s, list.filter((r) => r.status === s).length]));
check("roster has at least one alert", mix.alert > 0, mix);

// GET /api/c3/survivors/:id for every survivor
let detailOk = 0, demoHits = 0, flagged = 0, socialFlagged = 0, socialOk = 0;
const failures = [];
for (const r of list) {
  const d = await get(`/api/c3/survivors/${r.survivorId}`);
  const b = d.body;
  const n = b?.charts?.dates?.length;
  const ok = d.status === 200 && b.survivorId === r.survivorId && b.status === r.status && b.headline === r.headline &&
    typeof b.summary === "string" && Array.isArray(b.evidence) && b.evidence.length > 0 &&
    Array.isArray(b.recommendations) && b.recommendations.length > 0 && b.charts && n > 0 &&
    ["risk", "urgentRisk", "steps", "restingHeartRate", "hrv", "sleepHours", "doseDays"].every((k) => Array.isArray(b.charts[k]) && b.charts[k].length === n) &&
    typeof b.urgent === "boolean" && b.urgent === r.urgent && typeof b.urgentRisk === "number" && !("demo" in b);
  if (ok) detailOk++; else failures.push(r.survivorId);
  const needsSocial = r.status !== "ok" && (b.profile?.language !== "English" || b.profile?.livesAlone === "yes");
  if (needsSocial) { socialFlagged++; if (b.recommendations.some((x) => x.kind === "social")) socialOk++; }
  if (r === list[0]) responses[`/api/c3/survivors/${r.survivorId}`] = d;
  const demo = await get(`/api/c3/survivors/${r.survivorId}?demo=1`);
  if (r.status !== "ok") { flagged++; if (demo.body?.demo?.roughPatchStartsInDays) demoHits++; }
  if (r === list[0]) responses[`/api/c3/survivors/${r.survivorId}?demo=1`] = { status: demo.status, demo: demo.body?.demo };
}
check("every survivor panel matches the contract (and hides demo outcome)", detailOk === list.length, { ok: detailOk, failures });
check("flagged survivors who live alone or prefer another language get a social-needs action", socialOk === socialFlagged, { socialFlagged, socialOk });
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
  const H = met.body?.headline;
  check("metrics.headline: urgent, roughPatch (lift CI), realData, each with text",
    H && ["urgent", "roughPatch", "realData"].every((k) => typeof H[k]?.text === "string") &&
    H.roughPatch.liftCi95Points?.length === 2 && H.roughPatch.liftCi95Points[0] > 0 && H.order?.[0] === "urgent", H?.roughPatch);
  const FA = met.body?.fairness;
  const dims = (FA?.dimensions || []).map((x) => x.dimension);
  check("metrics.fairness: language, race, cancer type; each row has recall + CI or a too-few flag",
    ["preferred_language", "race_ethnicity", "cancer_type"].every((k) => dims.includes(k)) &&
    FA.dimensions.every((x) => x.rows.every((r) => r.tooFewToJudge ? !!r.note : (r.recallCi95?.length === 2 && r.recallCi95[0] <= r.recall && r.recall <= r.recallCi95[1]))),
    { summary: FA?.summary });
  const U = met.body?.urgent?.methods;
  check("urgent head beats schedule-only on ER recall and AUC", U && U.urgent.er_recall_2to7d > U.schedule.er_recall_2to7d && U.urgent.auc > U.schedule.auc, U && { urgent: U.urgent, schedule: U.schedule });
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
