#!/usr/bin/env node
// Regenerates CONTRACT.md from the real responses in runs/e2e-latest.json (run `npm run e2e` first).
import { readFileSync, writeFileSync } from "node:fs";

const run = JSON.parse(readFileSync("runs/e2e-latest.json", "utf8"));
const r = run.responses;
const roster = r["/api/c3/survivors"].body;
const idKey = Object.keys(r).find((k) => /survivors\/c3-P\d+$/.test(k));
const det = structuredClone(r[idKey].body);
for (const k of Object.keys(det.charts)) det.charts[k] = det.charts[k].slice(-5);
const demo = r[idKey + "?demo=1"].demo;
const met = r["/api/c3/metrics"].body;
const j = (x) => "```json\n" + JSON.stringify(x, null, 2) + "\n```";

writeFileSync("CONTRACT.md", `# C3 Bad Week Radar: API contract

Base URL (deployed): \`${run.base}\`. All responses are JSON with \`access-control-allow-origin: *\`.
The examples below are real responses, captured by \`npm run e2e\` on ${run.ranAt} and turned into this file by \`node scripts/contract.mjs\`. Chart arrays are cut to the last 5 points here; the API returns 42 days.

## \`GET /api/c3/survivors\`: roster tiles

Sorted by \`status\` (alert, then watch, then ok), then by risk. \`status\`: \`alert\` = rough patch predicted in the next 7 days; \`watch\` = raised risk; \`ok\` = near their usual. ${roster.length} survivors, showing 3:

${j(roster.slice(0, 3))}

## \`GET /api/c3/survivors/:id\`: survivor panel

Contract fields: \`survivorId, status, headline, summary, evidence, recommendations, charts\`. Extra fields: \`displayName\`, \`risk\` and \`scheduleRisk\` (0..1, the risk from the treatment calendar alone), \`thresholds\`, \`profile\`.

- \`evidence[]\`: the signals that drove this forecast, biggest first. \`riskShare\` = how much the 7-day risk drops if that signal were back at the person's normal (counterfactual on the model). A wearable signal is listed only if it moved the risk by 1 point or more AND moved in a worrying direction. The last item is always the treatment calendar, and its \`riskShare\` is the calendar-only risk.
- \`recommendations[]\`: \`{action, why, urgency}\`, where urgency is one of \`today\`, \`within 2 days\`, \`this week\` or \`routine\`. The coach does not diagnose: fever and infection signals route to the care team.
- \`charts\`: plain arrays, index-aligned with \`charts.dates\`. \`null\` = watch not worn or no check-in. \`doseDays\` is 1 on a treatment day. \`selfReportedFeeling\` is for display only and is not a model input.

${j(det)}

Add \`?demo=1\` to also get the hidden outcome (what really happened in the 14 days after the forecast). It is for the demo page only. The coach view must not show it:

${j({ demo })}

Unknown id: \`404 {"error":"survivor not found"}\`.

## \`GET /api/c3/metrics\`: held-out evaluation

Model and baselines on held-out patients. Includes the definition of a rough patch, plus a real-data check on the fatigue study. Methods: \`steps_rule\`, \`schedule\`, \`logistic\`, \`model\`. Excerpt:

${j({ asOf: met.asOf, definition: met.definition, counts: met.counts, model: met.methods.model, schedule: met.methods.schedule,
  realDataCheck: { next_day_auc_wearable_only_prev2days: met.realDataCheck.next_day_auc_wearable_only_prev2days,
    next_day_auc_yesterdays_self_rating: met.realDataCheck.next_day_auc_yesterdays_self_rating } })}

## \`GET /\`: standalone demo page

The roster, the survivor panel with charts, a "what happened next" reveal, and the metrics table.
`);
console.log("wrote CONTRACT.md");
