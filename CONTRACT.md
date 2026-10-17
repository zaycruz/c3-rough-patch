# C3 Bad Week Radar: API contract

Base URL (deployed): `https://c3-rough-patch.zay-259.workers.dev`. All responses are JSON with `access-control-allow-origin: *`.
The examples below are real responses, captured by `npm run e2e` on 2026-10-17T16:14:42.305Z and turned into this file by `node scripts/contract.mjs`. Chart arrays are cut to the last 5 points here; the API returns 42 days.

## `GET /api/c3/survivors`: roster tiles

Sorted with `urgent` first, then by `status` (alert, then watch, then ok), then by risk. `urgent` (boolean): the separate ER/hospital model flags an ER visit or admission risk in the next 7 days; an urgent survivor is always `alert`. Show it as a stronger badge and a "call today" action. `status`: `alert` = rough patch predicted in the next 7 days; `watch` = raised risk; `ok` = near their usual. 60 survivors, showing 3:

```json
[
  {
    "survivorId": "c3-P02185",
    "displayName": "P02185 · 42M · lymphoma",
    "status": "alert",
    "headline": "Urgent: ER or hospital risk 6% in the next 7 days, about 5x usual",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": true
  },
  {
    "survivorId": "c3-P03000",
    "displayName": "P03000 · 49M · kidney",
    "status": "alert",
    "headline": "Urgent: ER or hospital risk 10% in the next 7 days, about 9x usual",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": true
  },
  {
    "survivorId": "c3-P02465",
    "displayName": "P02465 · 59M · bladder",
    "status": "alert",
    "headline": "Rough patch risk 51% in the next 7 days, driven by sleep",
    "updatedAt": "2025-01-31T20:00:00Z",
    "urgent": false
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
  "survivorId": "c3-P02185",
  "displayName": "P02185 · 42M · lymphoma",
  "status": "alert",
  "headline": "Urgent: ER or hospital risk 6% in the next 7 days, about 5x usual",
  "summary": "Urgent: risk of an ER visit or hospital admission in the next 7 days is 6% (urgent line 6%, typical day 1.2%). Risk of a rough patch in the next 7 days: 22% (alert line 16%). The treatment calendar alone gives 9%; their check-ins move it +5 points and wearable signals +8. Biggest driver: Sleep efficiency 87% vs usual 92%, waking 3.5x a night vs 2.0x, 6.8 h asleep vs 7.1 h.",
  "urgent": true,
  "urgentRisk": 0.06,
  "risk": 0.221,
  "scheduleRisk": 0.091,
  "thresholds": {
    "alert": 0.156,
    "watch": 0.105,
    "urgent": 0.058
  },
  "profile": {
    "age": 42,
    "sex": "male",
    "cancerType": "lymphoma",
    "stage": "I",
    "treatmentPlan": "IV chemo every 21 days",
    "device": "Fitbit tracker",
    "language": "Haitian Creole",
    "livesAlone": "no",
    "context": "Day 5 of cycle 4 (IV chemo every 21 days)"
  },
  "evidence": [
    {
      "signal": "sleep",
      "label": "Sleep",
      "riskShare": 0.125,
      "value": 87,
      "baseline": 92,
      "unit": "% efficiency",
      "change": "-5 pts",
      "text": "Sleep efficiency 87% vs usual 92%, waking 3.5x a night vs 2.0x, 6.8 h asleep vs 7.1 h"
    },
    {
      "signal": "steps",
      "label": "Steps",
      "riskShare": 0.103,
      "value": 7721,
      "baseline": 12395,
      "unit": "steps/day",
      "change": "-38%",
      "text": "Steps 38% below their usual (7,721 vs 12,395 a day, last 3 days)"
    },
    {
      "signal": "checkins",
      "label": "Check-ins",
      "riskShare": 0.052,
      "value": 3,
      "baseline": 0,
      "unit": "check-ins skipped in a row",
      "change": "3 skipped",
      "text": "Skipped the last 3 daily check-ins (people report a rough day 1.4x as often after 3+ skips); 1 coaching call(s) missed or moved in 4 weeks; their last rating was their usual 4/5 (ratings up to 3 days ago)"
    },
    {
      "signal": "schedule",
      "label": "Treatment calendar",
      "riskShare": 0.091,
      "text": "Day 5 of cycle 4 (IV chemo every 21 days). The calendar alone predicts 9% risk of a rough patch this week."
    }
  ],
  "recommendations": [
    {
      "action": "Call today. Ask how they feel, about fever, fluids and anything new. If anything is off, have them call their care team now.",
      "why": "Their wearable pattern matches the days before an ER visit or hospital stay. The coach does not diagnose; the care team decides.",
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
      "action": "Send a short, no-pressure message asking how the week is going; offer a 2-minute call instead of the form.",
      "why": "3 daily check-ins skipped in a row; rough days are more common after a run of skips.",
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
      0.117,
      0.112,
      0.104,
      0.087,
      0.221
    ],
    "urgentRisk": [
      0.007,
      0.006,
      0.016,
      0.03,
      0.06
    ],
    "steps": [
      15018,
      9421,
      7779,
      7663,
      null
    ],
    "restingHeartRate": [
      76.4,
      78.9,
      77.4,
      79.7,
      null
    ],
    "hrv": [
      107,
      70.7,
      59,
      67.1,
      null
    ],
    "sleepHours": [
      6.23,
      7.37,
      6.37,
      7.13,
      null
    ],
    "skinTempChange": [
      null,
      null,
      null,
      null,
      null
    ],
    "watchWornHours": [
      22,
      24,
      21.2,
      19.6,
      3.4
    ],
    "doseDays": [
      1,
      0,
      0,
      0,
      0
    ],
    "selfReportedFeeling": [
      null,
      4,
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
    "roughPatchStartsInDays": null,
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
    "label_version": "v2",
    "rough_day": "relative to the person: daily feeling 1, or 2+ points below their own median of the last 28 check-ins (until 5 check-ins: feeling <= 2); OR on the weekly check-in any of fatigue, nausea, pain, appetite loss, diarrhea, trouble sleeping, anxiety, sadness >= 3 or 2+ above their own usual; OR ER visit / admission / treatment paused. Skipped check-ins are not counted as rough; they are shown to the coach as a warning sign (rough rate on return rises ~1.8x after 5 skips) with a same-day wearable estimate",
    "rough_patch": "a rough day followed by another within 3 days, or any clinical event; onset = first patch day after 7 quiet days",
    "forecast": "each evening, P(rough patch onset in the next 7 days); days already inside a patch are not scored",
    "early_warning": "an alert counts only if it fires 2+ days before onset",
    "inputs": "the person's own check-ins vs their usual (feeling, weekly symptoms; values up to 3 days ago), skipped check-ins and missed coaching calls, wearable signals vs personal baseline, wear time, known treatment schedule. No events, no diary text.",
    "split": "by patient: 60% train, 15% validation (thresholds), 25% test (all numbers below)",
    "alert_budget": "thresholds put 5% of quiet validation days on alert, same budget for every method"
  },
  "counts": {
    "patients": 3000,
    "test_patients": 750,
    "onsets_total": 3013,
    "label_missing_feeling_share": 0.545
  },
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
  },
  "realDataCheck": {
    "next_day_auc_wearable_only_prev2days": 0.482,
    "next_day_auc_yesterdays_self_rating": 0.64
  }
}
```

## `GET /`: standalone demo page

The roster, the survivor panel with charts, a "what happened next" reveal, and the metrics table.
