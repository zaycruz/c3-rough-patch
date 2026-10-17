# C3 Bad Week Radar: API contract

Base URL (deployed): `https://c3-rough-patch.zay-259.workers.dev`. All responses are JSON with `access-control-allow-origin: *`.
The examples below are real responses, captured by `npm run e2e` on 2026-10-17T17:42:32.390Z and turned into this file by `node scripts/contract.mjs`. Chart arrays are cut to the last 5 points here; the API returns 42 days.

## `GET /api/c3/survivors`: roster tiles

Returned in **priority order**. Use `priority` (1 = call first) or `tier` for ordering; do not re-sort.

| Field | Meaning |
|---|---|
| `tier` | `urgent` > `alert` > `watch` > `ok`. **First-class ordering field.** `urgent` = the separate ER/hospital model flags an ER visit or admission risk in the next 7 days. Show it first, as a stronger badge with a "call today" action. |
| `priority` | 1..n. Urgent survivors first (highest ER risk first), then alert, watch, ok, each by rough-patch risk. |
| `status` | `alert` = rough patch predicted in the next 7 days (top 5% of days, about one new alert per coach per day); `watch` = raised risk (top 12%); `ok` = near their usual. An urgent survivor is always `alert`. |
| `urgent` | Boolean, same as `tier === "urgent"`. |
| `risk` | 0..1. P(rough patch starts in the next 7 days). |
| `urgentRisk` | 0..1. P(ER visit or admission in the next 7 days). Typical day: 1.2%. |

The original contract keys (`survivorId, displayName, status, headline, updatedAt`) are unchanged; the other fields were added. 60 survivors, showing 3:

```json
[
  {
    "survivorId": "c3-P03000",
    "displayName": "P03000 · 49M · kidney",
    "status": "alert",
    "headline": "Urgent review: about 6x the usual ER or hospital risk this week. A prompt to check in, not a prediction",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": true,
    "tier": "urgent",
    "priority": 1,
    "risk": 0.078,
    "urgentRisk": 0.104,
    "reviewToday": false
  },
  {
    "survivorId": "c3-P02185",
    "displayName": "P02185 · 42M · lymphoma",
    "status": "alert",
    "headline": "Urgent review: about 6x the usual ER or hospital risk this week. A prompt to check in, not a prediction",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": true,
    "tier": "urgent",
    "priority": 2,
    "risk": 0.221,
    "urgentRisk": 0.06,
    "reviewToday": false
  },
  {
    "survivorId": "c3-P02465",
    "displayName": "P02465 · 59M · bladder",
    "status": "alert",
    "headline": "Rough patch risk 51% in the next 7 days, driven by sleep",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": false,
    "tier": "alert",
    "priority": 3,
    "risk": 0.507,
    "urgentRisk": 0.001,
    "reviewToday": false
  }
]
```

## `GET /api/c3/survivors/:id`: survivor panel

Contract fields: `survivorId, status, headline, summary, evidence, recommendations, charts`. Extra fields: `displayName`, `tier`, `priority`, `urgent`, `urgentRisk`, `risk` and `scheduleRisk` (0..1, the risk from the treatment calendar alone), `thresholds` (alert, watch and urgent lines), and `profile` (including `language` and `livesAlone`).

- `evidence[]`: the signals that drove this forecast, biggest first. `signal` is one of `checkins` (the person's own ratings and symptoms vs their usual, skipped check-ins, missed calls), `steps`, `resting_heart_rate`, `hrv_rmssd_ms`, `sleep`, `skin_temp_change_c`, `wear` or `schedule`. `riskShare` = how much the 7-day risk drops if that signal were back at the person's normal (counterfactual on the model). A signal is listed only if it moved the risk by 1 point or more AND moved in a worrying direction. The last item is always the treatment calendar, and its `riskShare` is the calendar-only risk.
- `recommendations[]`: `{action, why, urgency, kind?}`, where urgency is one of `today`, `within 2 days`, `this week` or `routine`. `kind: "social"` marks social-needs actions: preferred language not English, or lives alone. These are given only to flagged survivors. The coach does not diagnose: fever and infection signals route to the care team.
- `charts`: plain arrays, index-aligned with `charts.dates`. `null` = watch not worn or no check-in. `doseDays` is 1 on a treatment day. `selfReportedFeeling` is the daily rating; the model uses ratings only up to 3 days back, plus skipped check-ins up to today.

```json
{
  "survivorId": "c3-P03000",
  "displayName": "P03000 · 49M · kidney",
  "status": "alert",
  "headline": "Urgent review: about 6x the usual ER or hospital risk this week. A prompt to check in, not a prediction",
  "summary": "Urgent review: their wearable and calendar pattern puts them in the top 3% for ER or hospital risk. Flags like this carry about 6x the usual risk, but most are false alarms: about 1 in 14 is followed by an ER visit or admission within 7 days. Risk of a rough patch in the next 7 days: 8% (alert line 16%). The treatment calendar alone gives 2%; their check-ins move it +0 points and wearable signals +6. Biggest driver: Sleep efficiency 82% vs usual 88%, waking 3.0x a night vs 2.0x, 6.4 h asleep vs 6.9 h.",
  "urgent": true,
  "urgentRisk": 0.104,
  "reviewToday": false,
  "noteFlag": null,
  "risk": 0.078,
  "scheduleRisk": 0.021,
  "thresholds": {
    "alert": 0.156,
    "watch": 0.105,
    "urgent": 0.058
  },
  "profile": {
    "age": 49,
    "sex": "male",
    "cancerType": "kidney",
    "stage": "I",
    "treatmentPlan": "Immunotherapy every 21 days",
    "device": "Fitbit smartwatch",
    "language": "Spanish",
    "livesAlone": "no",
    "context": "Day 16 of cycle 3 (Immunotherapy every 21 days)"
  },
  "evidence": [
    {
      "signal": "sleep",
      "label": "Sleep",
      "riskShare": 0.063,
      "value": 82.3,
      "baseline": 88,
      "unit": "% efficiency",
      "change": "-6 pts",
      "text": "Sleep efficiency 82% vs usual 88%, waking 3.0x a night vs 2.0x, 6.4 h asleep vs 6.9 h"
    },
    {
      "signal": "resting_heart_rate",
      "label": "Resting heart rate",
      "riskShare": 0.034,
      "value": 88.4,
      "baseline": 85.6,
      "unit": "bpm",
      "change": "+2.8 bpm",
      "text": "Resting heart rate +2.8 bpm vs their usual (88 vs 86)"
    },
    {
      "signal": "schedule",
      "label": "Treatment calendar",
      "riskShare": 0.021,
      "text": "Day 16 of cycle 3 (Immunotherapy every 21 days). The calendar alone predicts 2% risk of a rough patch this week."
    }
  ],
  "recommendations": [
    {
      "action": "Call today. Ask how they feel, about fever, fluids and anything new. If anything is off, have them call their care team now.",
      "why": "Their wearable pattern looks like the days before an ER visit or hospital stay (about 6x the usual risk; about 1 in 14 such flags is followed by one). The coach does not diagnose; the care team decides.",
      "urgency": "today"
    },
    {
      "action": "Check in this week about sleep: nights, naps, worries. Share the sleep tips sheet.",
      "why": "Sleep got shorter or more broken than usual.",
      "urgency": "within 2 days"
    },
    {
      "action": "Move the next coaching call earlier and plan around the expected low point.",
      "why": "The forecast covers the next 7 days.",
      "urgency": "this week"
    },
    {
      "action": "Reach out in Spanish, or book an interpreter for the call.",
      "why": "Their preferred language is Spanish; a rough week is harder to describe in a second language.",
      "urgency": "this week",
      "kind": "social"
    }
  ],
  "charts": {
    "dates": [
      "2025-01-27",
      "2025-01-28",
      "2025-01-29",
      "2025-01-30",
      "2025-01-31"
    ],
    "risk": [
      0.02,
      0.019,
      0.018,
      0.02,
      0.078
    ],
    "urgentRisk": [
      0.003,
      0.003,
      0.005,
      0.009,
      0.104
    ],
    "steps": [
      1379,
      1545,
      2242,
      2390,
      3173
    ],
    "restingHeartRate": [
      86.4,
      85.3,
      88.4,
      86.8,
      90
    ],
    "hrv": [
      30,
      31.6,
      23.9,
      25.3,
      23.6
    ],
    "sleepHours": [
      7.1,
      6.68,
      5.85,
      7.1,
      6.22
    ],
    "skinTempChange": [
      -0.38,
      0.55,
      -0.19,
      0.55,
      -0.45
    ],
    "watchWornHours": [
      20.2,
      22,
      21.1,
      13.4,
      21
    ],
    "doseDays": [
      0,
      0,
      0,
      0,
      0
    ],
    "selfReportedFeeling": [
      null,
      null,
      2,
      2,
      2
    ]
  },
  "tier": "urgent",
  "priority": 1
}
```

Add `?demo=1` to also get the hidden outcome (what really happened in the 14 days after the forecast). It is for the demo page only. The coach view must not show it:

```json
{
  "demo": {
    "note": "Hidden from the coach view: what actually happened in the 14 days after the forecast.",
    "roughPatchStartsInDays": null,
    "erOrAdmissionInDays": null,
    "events": [
      "2025-02-06: treatment paused"
    ]
  }
}
```

Unknown id: `404 {"error":"survivor not found"}`.

## `GET /api/c3/metrics`: held-out evaluation

All numbers are from held-out test patients (750 patients the model never saw).

**Show these first: `headline`** (ready-made text plus the numbers behind it, in `headline.order`):

```json
{
  "urgent": {
    "baseline": "Calendar-only ER model (treatment calendar only, same 3% urgent budget)",
    "text": "Urgent ER tier: catches 47% of ER visits and hospital admissions 2-7 days early vs 36% for the calendar-only ER model at the same 3% budget (95% CI +2 to +19 points). An urgent flag means about 6x the usual risk, not a prediction: about 1 in 14 is followed by an ER visit or admission within 7 days.",
    "erCaught": 0.467,
    "erCaughtCalendar": 0.363,
    "liftCi95Points": [
      2,
      19
    ],
    "flagPrecision": 0.074,
    "baseRate": 0.0119,
    "timesUsualRisk": 6.2,
    "flagsPerPatientMonth": 0.38
  },
  "noteScan": {
    "baseline": "Urgent ER tier alone",
    "text": "Diary-note safety scan (English, Spanish, Haitian Creole word list): a red-flag note (fever or chills, can't keep fluids down, called the nurse) is followed by an ER visit or admission 27% of the time, about 23x the usual. With the urgent tier it catches 57% of ER visits 2-7 days early vs 47% for the tier alone (95% CI +6 to +15 points), for 5% more flags. No gain yet for Haitian Creole speakers: in this data their Creole notes never describe a red flag.",
    "erCaught": 0.566,
    "erCaughtUrgentOnly": 0.467,
    "gainCi95Points": [
      5.5,
      14.9
    ],
    "flagPrecision": 0.273,
    "timesUsualRisk": 23,
    "byLanguage": {
      "English": {
        "patients": 445,
        "er_events": 107,
        "calendar": 0.364,
        "urgent": 0.505,
        "urgent_or_note": 0.598
      },
      "Haitian Creole": {
        "patients": 60,
        "er_events": 18,
        "calendar": 0.5,
        "urgent": 0.444,
        "urgent_or_note": 0.444
      },
      "Spanish": {
        "patients": 245,
        "er_events": 57,
        "calendar": 0.316,
        "urgent": 0.404,
        "urgent_or_note": 0.544
      }
    },
    "examples": [
      {
        "noteLanguage": "English",
        "category": "called_care_team",
        "note": "Called the nurse line, they said come in if it goes over 100.4",
        "patientId": "P00034",
        "erOrAdmissionWithin7Days": true
      },
      {
        "noteLanguage": "English",
        "category": "cant_keep_fluids",
        "note": "Threw up twice, couldn't keep water down",
        "patientId": "P00080",
        "erOrAdmissionWithin7Days": false
      },
      {
        "noteLanguage": "English",
        "category": "distress",
        "note": "Worst day so far.",
        "patientId": "P00034",
        "erOrAdmissionWithin7Days": false
      },
      {
        "noteLanguage": "English",
        "category": "fever_infection",
        "note": "Chills tonight, took my temp 100.8",
        "patientId": "P00034",
        "erOrAdmissionWithin7Days": true
      },
      {
        "noteLanguage": "Spanish",
        "category": "called_care_team",
        "note": "Llamé a la enfermera, dijo que vaya si pasa de 38. Gracias a Dios por mis vecinos.",
        "patientId": "P02634",
        "erOrAdmissionWithin7Days": false
      },
      {
        "noteLanguage": "Spanish",
        "category": "cant_keep_fluids",
        "note": "Vomité dos veces.",
        "patientId": "P00054",
        "erOrAdmissionWithin7Days": false
      },
      {
        "noteLanguage": "Spanish",
        "category": "distress",
        "note": "El peor día hasta ahora.",
        "patientId": "P00228",
        "erOrAdmissionWithin7Days": false
      },
      {
        "noteLanguage": "Spanish",
        "category": "fever_infection",
        "note": "Me duele todo el cuerpo como gripe",
        "patientId": "P00054",
        "erOrAdmissionWithin7Days": false
      }
    ]
  },
  "roughPatch": {
    "baseline": "Calendar-only rough-patch model (treatment calendar only, same 5% alert budget)",
    "text": "Catches 48% of rough patches 2-7 days early vs 36% for the calendar-only rough-patch model (95% CI +8 to +15 points), at the same alert budget of about one new alert per coach per day. This lead time is shown on synthetic data only: on real people the wearable did not predict the next day (AUC 0.482).",
    "caught": 0.476,
    "caughtCalendar": 0.359,
    "liftCi95Points": [
      7.8,
      15.2
    ],
    "alertPrecision": 0.184,
    "alertPrecisionCalendar": 0.106,
    "alertsPerPatientMonth": 0.48,
    "medianLeadDays": 6,
    "alertBudget": "thresholds put 5% of quiet validation days on alert, same budget for every method",
    "syntheticOnly": true,
    "realDataNextDayAuc": 0.482
  },
  "realData": {
    "text": "On real data (fatigue study, 204 people), wearables confirm a bad day but do not predict one (next-day AUC 0.482); the person's own rating does better (0.64). Proving lead time on real people needs the wearable, daily check-ins and dated ER visits and admissions for a few hundred survivors on treatment over several months; the public studies we found have the wearable and ratings but no clinical events.",
    "nextDayAucWearable": 0.482,
    "nextDayAucSelfRating": 0.64
  },
  "order": [
    "urgent",
    "noteScan",
    "roughPatch",
    "realData"
  ]
}
```

**Fairness: `fairness`.** Recall at the alert line by language, race and ethnicity, cancer type, sex, age, living alone and device. Each row has a 95% CI from resampling patients. Groups with fewer than 30 rough weeks have `tooFewToJudge: true` and no numbers. `belowOverall` = the whole CI is below the overall recall. Language dimension:

```json
{
  "metric": "week-level recall at the alert line (share of rough weeks that got an alert), held-out patients",
  "overallRecall": 0.276,
  "summary": "Recall is clearly below the overall 28% (whole CI below it) for: Cancer type sarcoma (13%, CI 0%-26%). Lower, but the CI still reaches the overall (too few patients to be sure): Language Haitian Creole (22%, CI 10%-36%); Cancer type breast (21%, CI 14%-28%). Groups with fewer than 30 rough weeks are marked too few to judge.",
  "dimensions": [
    {
      "dimension": "preferred_language",
      "label": "Language",
      "rows": [
        {
          "group": "English",
          "patients": 445,
          "roughWeeks": 409,
          "recall": 0.267,
          "recallCi95": [
            0.216,
            0.312
          ],
          "precision": 0.218,
          "auc": 0.818,
          "tooFewToJudge": false,
          "belowOverall": false
        },
        {
          "group": "Haitian Creole",
          "patients": 60,
          "roughWeeks": 60,
          "recall": 0.217,
          "recallCi95": [
            0.103,
            0.358
          ],
          "precision": 0.22,
          "auc": 0.828,
          "tooFewToJudge": false,
          "belowOverall": false,
          "lowerButUncertain": true
        },
        {
          "group": "Spanish",
          "patients": 245,
          "roughWeeks": 216,
          "recall": 0.31,
          "recallCi95": [
            0.252,
            0.374
          ],
          "precision": 0.261,
          "auc": 0.845,
          "tooFewToJudge": false,
          "belowOverall": false
        }
      ]
    }
  ]
}
```

**Key map** (everything else in the response):

| Key | What it holds |
|---|---|
| `methods.{model,schedule,logistic,steps_rule}` | One entry per method, each `{name, weeks:{weeks, rough_weeks, auc, precision, recall, alert_share}, episodes:{episodes, episode_recall, median_lead_days, lead_days_hist, er_admissions, er_recall, alert_runs, alert_precision, alerts_per_patient_month}}`. `model` is the Radar; `schedule` is the treatment-calendar-only baseline (same learner). Every method uses the same alert budget. |
| `lift_vs_schedule_ci95` | 95% CI (patient bootstrap) for model minus calendar: `episode_recall_diff` and `er_recall_diff`, as fractions. |
| `ablation_without_checkins` | The same learner without the check-in inputs, plus `lift_of_checkins_ci95`. |
| `urgent` | The ER/admission tier: `definition`, `methods.{urgent,schedule,radar}` (`er_recall_2to7d, median_lead_days, flag_precision, flags_per_patient_month, auc, average_precision, base_rate`), `names`, `calibration`. |
| `calibration.{model,schedule}` | `brier`, `brier_if_base_rate`, and `deciles[]` of `{predicted, observed, days}`. |
| `subgroups` | Raw per-group numbers behind `fairness` (snake_case). |
| `definition` | What a rough day, patch, onset and alert mean; `inputs`; `alert_budget`; `label_version`. |
| `label_v2` | Label diagnostics: skip-run rough rates (`rough_rate_after_skips`), onsets by source and by engagement, and the cross-check against the v1 label. |
| `counts`, `feature_importance_auc_drop`, `realDataCheck` | Dataset counts; global drivers (AUC drop when a feature is shuffled); real fatigue-study check. |

Excerpt of `methods.model` and `methods.schedule`:

```json
{
  "model": {
    "name": "Radar (gradient boosting, check-ins + wearable + schedule)",
    "weeks": {
      "weeks": 14501,
      "rough_weeks": 685,
      "auc": 0.827,
      "precision": 0.231,
      "recall": 0.276,
      "alert_share": 0.056
    },
    "episodes": {
      "episodes": 721,
      "episode_recall": 0.476,
      "median_lead_days": 6,
      "lead_days_hist": {
        "2": 50,
        "3": 33,
        "4": 34,
        "5": 43,
        "6": 51,
        "7": 132
      },
      "er_admissions": 182,
      "er_recall": 0.363,
      "alert_runs": 1838,
      "alert_precision": 0.184,
      "alerts_per_patient_month": 0.48
    }
  },
  "schedule": {
    "name": "Baseline: treatment schedule only (same learner)",
    "weeks": {
      "weeks": 14501,
      "rough_weeks": 685,
      "auc": 0.808,
      "precision": 0.197,
      "recall": 0.257,
      "alert_share": 0.062
    },
    "episodes": {
      "episodes": 721,
      "episode_recall": 0.359,
      "median_lead_days": 7,
      "lead_days_hist": {
        "2": 18,
        "3": 27,
        "4": 16,
        "5": 16,
        "6": 26,
        "7": 156
      },
      "er_admissions": 182,
      "er_recall": 0.22,
      "alert_runs": 1368,
      "alert_precision": 0.106,
      "alerts_per_patient_month": 0.36
    }
  }
}
```

## `GET /`: standalone demo page

The roster, the survivor panel with charts, a "what happened next" reveal, and the metrics table.
