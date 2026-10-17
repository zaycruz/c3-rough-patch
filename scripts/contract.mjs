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

Returned in **priority order**. Use \`priority\` (1 = call first) or \`tier\` for ordering; do not re-sort.

| Field | Meaning |
|---|---|
| \`tier\` | \`urgent\` > \`alert\` > \`watch\` > \`ok\`. **First-class ordering field.** \`urgent\` = the separate ER/hospital model flags an ER visit or admission risk in the next 7 days. Show it first, as a stronger badge with a "call today" action. |
| \`priority\` | 1..n. Urgent survivors first (highest ER risk first), then alert, watch, ok, each by rough-patch risk. |
| \`status\` | \`alert\` = rough patch predicted in the next 7 days (top 5% of days, about one new alert per coach per day); \`watch\` = raised risk (top 12%); \`ok\` = near their usual. An urgent survivor is always \`alert\`. |
| \`urgent\` | Boolean, same as \`tier === "urgent"\`. |
| \`risk\` | 0..1. P(rough patch starts in the next 7 days). |
| \`urgentRisk\` | 0..1. P(ER visit or admission in the next 7 days). Typical day: 1.2%. |

The original contract keys (\`survivorId, displayName, status, headline, updatedAt\`) are unchanged; the other fields were added. ${roster.length} survivors, showing 3:

${j(roster.slice(0, 3))}

## \`GET /api/c3/survivors/:id\`: survivor panel

Contract fields: \`survivorId, status, headline, summary, evidence, recommendations, charts\`. Extra fields: \`displayName\`, \`tier\`, \`priority\`, \`urgent\`, \`urgentRisk\`, \`risk\` and \`scheduleRisk\` (0..1, the risk from the treatment calendar alone), \`thresholds\` (alert, watch and urgent lines), and \`profile\` (including \`language\` and \`livesAlone\`).

- \`evidence[]\`: the signals that drove this forecast, biggest first. \`signal\` is one of \`checkins\` (the person's own ratings and symptoms vs their usual, skipped check-ins, missed calls), \`steps\`, \`resting_heart_rate\`, \`hrv_rmssd_ms\`, \`sleep\`, \`skin_temp_change_c\`, \`wear\` or \`schedule\`. \`riskShare\` = how much the 7-day risk drops if that signal were back at the person's normal (counterfactual on the model). A signal is listed only if it moved the risk by 1 point or more AND moved in a worrying direction. The last item is always the treatment calendar, and its \`riskShare\` is the calendar-only risk.
- \`recommendations[]\`: \`{action, why, urgency, kind?}\`, where urgency is one of \`today\`, \`within 2 days\`, \`this week\` or \`routine\`. \`kind: "social"\` marks social-needs actions: preferred language not English, or lives alone. These are given only to flagged survivors. The coach does not diagnose: fever and infection signals route to the care team.
- \`charts\`: plain arrays, index-aligned with \`charts.dates\`. \`null\` = watch not worn or no check-in. \`doseDays\` is 1 on a treatment day. \`selfReportedFeeling\` is the daily rating; the model uses ratings only up to 3 days back, plus skipped check-ins up to today.

${j(det)}

Add \`?demo=1\` to also get the hidden outcome (what really happened in the 14 days after the forecast). It is for the demo page only. The coach view must not show it:

${j({ demo })}

Unknown id: \`404 {"error":"survivor not found"}\`.

## \`GET /api/c3/metrics\`: held-out evaluation

All numbers are from held-out test patients (${met.counts.test_patients} patients the model never saw).

**Show these first: \`headline\`** (ready-made text plus the numbers behind it, in \`headline.order\`):

${j(met.headline)}

**Fairness: \`fairness\`.** Recall at the alert line by language, race and ethnicity, cancer type, sex, age, living alone and device. Each row has a 95% CI from resampling patients. Groups with fewer than 30 rough weeks have \`tooFewToJudge: true\` and no numbers. \`belowOverall\` = the whole CI is below the overall recall. Language dimension:

${j({ metric: met.fairness.metric, overallRecall: met.fairness.overallRecall, summary: met.fairness.summary,
  dimensions: met.fairness.dimensions.filter((x) => x.dimension === "preferred_language") })}

**Key map** (everything else in the response):

| Key | What it holds |
|---|---|
| \`methods.{model,schedule,logistic,steps_rule}\` | One entry per method, each \`{name, weeks:{weeks, rough_weeks, auc, precision, recall, alert_share}, episodes:{episodes, episode_recall, median_lead_days, lead_days_hist, er_admissions, er_recall, alert_runs, alert_precision, alerts_per_patient_month}}\`. \`model\` is the Radar; \`schedule\` is the treatment-calendar-only baseline (same learner). Every method uses the same alert budget. |
| \`lift_vs_schedule_ci95\` | 95% CI (patient bootstrap) for model minus calendar: \`episode_recall_diff\` and \`er_recall_diff\`, as fractions. |
| \`ablation_without_checkins\` | The same learner without the check-in inputs, plus \`lift_of_checkins_ci95\`. |
| \`urgent\` | The ER/admission tier: \`definition\`, \`methods.{urgent,schedule,radar}\` (\`er_recall_2to7d, median_lead_days, flag_precision, flags_per_patient_month, auc, average_precision, base_rate\`), \`names\`, \`calibration\`. |
| \`calibration.{model,schedule}\` | \`brier\`, \`brier_if_base_rate\`, and \`deciles[]\` of \`{predicted, observed, days}\`. |
| \`subgroups\` | Raw per-group numbers behind \`fairness\` (snake_case). |
| \`definition\` | What a rough day, patch, onset and alert mean; \`inputs\`; \`alert_budget\`; \`label_version\`. |
| \`label_v2\` | Label diagnostics: skip-run rough rates (\`rough_rate_after_skips\`), onsets by source and by engagement, and the cross-check against the v1 label. |
| \`counts\`, \`feature_importance_auc_drop\`, \`realDataCheck\` | Dataset counts; global drivers (AUC drop when a feature is shuffled); real fatigue-study check. |

Excerpt of \`methods.model\` and \`methods.schedule\`:

${j({ model: met.methods.model, schedule: met.methods.schedule })}

## \`GET /\`: standalone demo page

The roster, the survivor panel with charts, a "what happened next" reveal, and the metrics table.
`);
console.log("wrote CONTRACT.md");
