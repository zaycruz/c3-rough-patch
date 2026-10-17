# C3 Bad Week Radar: API contract

Base URL (deployed): `https://c3-rough-patch.zay-259.workers.dev`. All responses are JSON with `access-control-allow-origin: *`.
The examples below are real responses, captured by `npm run e2e` on 2026-10-17T14:21:41.679Z and turned into this file by `node scripts/contract.mjs`. Chart arrays are cut to the last 5 points here; the API returns 42 days.

## `GET /api/c3/survivors`: roster tiles

Sorted by `status` (alert, then watch, then ok), then by risk. `status`: `alert` = rough patch predicted in the next 7 days; `watch` = raised risk; `ok` = near their usual. 60 survivors, showing 3:

```json
[
  {
    "survivorId": "c3-P02465",
    "displayName": "P02465 · 59M · bladder",
    "status": "alert",
    "headline": "Rough patch risk 51% in the next 7 days, driven by sleep",
    "updatedAt": "2025-01-31T20:00:00Z"
  },
  {
    "survivorId": "c3-P02836",
    "displayName": "P02836 · 52M · lung",
    "status": "alert",
    "headline": "Rough patch risk 24% in the next 7 days, mostly from the treatment calendar",
    "updatedAt": "2025-01-31T20:00:00Z"
  },
  {
    "survivorId": "c3-P01289",
    "displayName": "P01289 · 62M · bladder",
    "status": "alert",
    "headline": "Rough patch risk 17% in the next 7 days, mostly from the treatment calendar",
    "updatedAt": "2025-01-31T20:00:00Z"
  }
]
```

## `GET /api/c3/survivors/:id`: survivor panel

Contract fields: `survivorId, status, headline, summary, evidence, recommendations, charts`. Extra fields: `displayName`, `risk` and `scheduleRisk` (0..1, the risk from the treatment calendar alone), `thresholds`, `profile`.

- `evidence[]`: the signals that drove this forecast, biggest first. `riskShare` = how much the 7-day risk drops if that signal were back at the person's normal (counterfactual on the model). A wearable signal is listed only if it moved the risk by 1 point or more AND moved in a worrying direction. The last item is always the treatment calendar, and its `riskShare` is the calendar-only risk.
- `recommendations[]`: `{action, why, urgency}`, where urgency is one of `today`, `within 2 days`, `this week` or `routine`. The coach does not diagnose: fever and infection signals route to the care team.
- `charts`: plain arrays, index-aligned with `charts.dates`. `null` = watch not worn or no check-in. `doseDays` is 1 on a treatment day. `selfReportedFeeling` is for display only and is not a model input.

```json
{
  "survivorId": "c3-P02465",
  "displayName": "P02465 · 59M · bladder",
  "status": "alert",
  "headline": "Rough patch risk 51% in the next 7 days, driven by sleep",
  "summary": "Risk of a rough patch in the next 7 days: 51% (alert line 13%). The treatment calendar alone gives 2%; wearable signals move it +48 points. Biggest wearable driver: Sleep efficiency 62% vs usual 74%, waking 8.0x a night vs 1.0x, 7.7 h asleep vs 8.0 h.",
  "risk": 0.506,
  "scheduleRisk": 0.023,
  "thresholds": {
    "alert": 0.133,
    "watch": 0.087
  },
  "profile": {
    "age": 59,
    "sex": "male",
    "cancerType": "bladder",
    "stage": "III",
    "treatmentPlan": "IV chemo every 21 days",
    "device": "Fitbit smartwatch",
    "language": "Spanish",
    "livesAlone": "yes",
    "context": "Day 14 of cycle 2 (IV chemo every 21 days)"
  },
  "evidence": [
    {
      "signal": "sleep",
      "label": "Sleep",
      "riskShare": 0.415,
      "value": 62,
      "baseline": 74.5,
      "unit": "% efficiency",
      "change": "-12 pts",
      "text": "Sleep efficiency 62% vs usual 74%, waking 8.0x a night vs 1.0x, 7.7 h asleep vs 8.0 h"
    },
    {
      "signal": "resting_heart_rate",
      "label": "Resting heart rate",
      "riskShare": 0.253,
      "value": 72.5,
      "baseline": 69,
      "unit": "bpm",
      "change": "+3.5 bpm",
      "text": "Resting heart rate +3.5 bpm vs their usual (72 vs 69)"
    },
    {
      "signal": "steps",
      "label": "Steps",
      "riskShare": 0.144,
      "value": 476,
      "baseline": 1310,
      "unit": "steps/day",
      "change": "-64%",
      "text": "Steps 64% below their usual (476 vs 1,310 a day, last 3 days)"
    },
    {
      "signal": "schedule",
      "label": "Treatment calendar",
      "riskShare": 0.023,
      "text": "Day 14 of cycle 2 (IV chemo every 21 days). The calendar alone predicts 2% risk of a rough patch this week."
    }
  ],
  "recommendations": [
    {
      "action": "Check in this week about sleep: nights, naps, worries. Share the sleep tips sheet.",
      "why": "Sleep got shorter or more broken than usual.",
      "urgency": "within 2 days"
    },
    {
      "action": "Move the next coaching call earlier and plan around the expected low point.",
      "why": "The forecast covers the next 7 days.",
      "urgency": "this week"
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
      0.048,
      0.037,
      0.016,
      0.046,
      0.506
    ],
    "steps": [
      1496,
      802,
      null,
      null,
      476
    ],
    "restingHeartRate": [
      66.1,
      70.6,
      null,
      null,
      72.5
    ],
    "hrv": [
      35,
      31.2,
      null,
      null,
      18.1
    ],
    "sleepHours": [
      7.85,
      7.38,
      null,
      null,
      7.73
    ],
    "skinTempChange": [
      0.36,
      0.92,
      null,
      null,
      0.48
    ],
    "watchWornHours": [
      22.7,
      20.3,
      1.2,
      0.9,
      20.3
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
      5,
      null,
      null,
      null
    ]
  }
}
```

Add `?demo=1` to also get the hidden outcome (what really happened in the 14 days after the forecast). It is for the demo page only. The coach view must not show it:

```json
{
  "demo": {
    "note": "Hidden from the coach view: what actually happened in the 14 days after the forecast.",
    "roughPatchStartsInDays": 1,
    "erOrAdmissionInDays": null,
    "events": []
  }
}
```

Unknown id: `404 {"error":"survivor not found"}`.

## `GET /api/c3/metrics`: held-out evaluation

Model and baselines on held-out patients. Includes the definition of a rough patch, plus a real-data check on the fatigue study. Methods: `steps_rule`, `schedule`, `logistic`, `model`. Excerpt:

```json
{
  "asOf": "2025-01-31",
  "definition": {
    "rough_day": "daily feeling <= 2, OR weekly fatigue >= 3, OR ER visit / hospital admission / treatment paused",
    "rough_patch": "a rough day followed by another within 3 days, or any clinical event; onset = first patch day after 7 quiet days",
    "forecast": "each evening, P(rough patch onset in the next 7 days); days already inside a patch are not scored",
    "early_warning": "an alert counts only if it fires 2+ days before onset",
    "inputs": "wearable signals vs personal baseline, wear time, known treatment schedule. No self-reports, no events.",
    "split": "by patient: 60% train, 15% validation (thresholds), 25% test (all numbers below)",
    "alert_budget": "thresholds put 12% of quiet validation days on alert, same budget for every method"
  },
  "counts": {
    "patients": 3000,
    "test_patients": 750,
    "onsets_total": 3677,
    "label_missing_feeling_share": 0.545
  },
  "model": {
    "name": "Radar (gradient boosting, wearable + schedule)",
    "weeks": {
      "weeks": 14216,
      "rough_weeks": 786,
      "auc": 0.804,
      "precision": 0.195,
      "recall": 0.439,
      "alert_share": 0.125
    },
    "episodes": {
      "episodes": 867,
      "episode_recall": 0.642,
      "median_lead_days": 6,
      "lead_days_hist": {
        "2": 71,
        "3": 56,
        "4": 53,
        "5": 67,
        "6": 89,
        "7": 221
      },
      "er_admissions": 182,
      "er_recall": 0.544,
      "alert_runs": 3192,
      "alert_precision": 0.147,
      "alerts_per_patient_month": 0.84
    }
  },
  "schedule": {
    "name": "Baseline: treatment schedule only (same learner)",
    "weeks": {
      "weeks": 14216,
      "rough_weeks": 786,
      "auc": 0.79,
      "precision": 0.184,
      "recall": 0.403,
      "alert_share": 0.121
    },
    "episodes": {
      "episodes": 867,
      "episode_recall": 0.589,
      "median_lead_days": 6,
      "lead_days_hist": {
        "2": 52,
        "3": 33,
        "4": 42,
        "5": 54,
        "6": 79,
        "7": 251
      },
      "er_admissions": 182,
      "er_recall": 0.418,
      "alert_runs": 2567,
      "alert_precision": 0.139,
      "alerts_per_patient_month": 0.67
    }
  },
  "realDataCheck": {
    "next_day_auc_wearable_only_prev2days": 0.482,
    "next_day_auc_yesterdays_self_rating": 0.64
  }
}
```

## `GET /`: standalone demo page

The roster, the survivor panel with charts, a "what happened next" reveal, and the metrics table.
