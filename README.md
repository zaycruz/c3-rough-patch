# C3 Bad Week Radar

Coach Console module for challenge "The Bad Week Radar" (eMerge hackathon, Healthcare track, Sylvester).
It watches a survivor's wearable and treatment calendar. Every evening it forecasts whether a rough patch will start in the next 7 days, explains which signals drove the forecast, and gives the coach a suggested action.

- Live: https://c3-rough-patch.zay-259.workers.dev (demo page) · API under `/api/c3`. See [CONTRACT.md](CONTRACT.md).
- Stack: TypeScript Cloudflare Worker (no LLM step needed). The model is trained offline in Python and its outputs are baked into `src/data/*.json`.

## What counts as a rough patch (and why)

"Rough patch" is not a column in the data, so we define it from what the person and the clinic report:

- **Rough day**: daily feeling of 2 or less (on a 1 to 5 scale), OR weekly fatigue of 3 or more (0 to 4), OR an ER visit, hospital admission or treatment pause.
- **Rough patch**: a rough day with another rough day within 3 days, or any clinical event. One bad day is not a patch.
- **Onset**: the first patch day after 7 quiet days. Days already inside a patch are not scored. Being sick already does not count as a hit.

Why this definition: it combines how the person feels (what a coach cares about) with clinical events (what matters most). One caveat: 55% of daily-feeling check-ins are missing, and people skip more on bad days, so this label **under-counts** rough patches.

**Inputs are wearable and calendar only**: steps, active minutes, resting heart rate, HRV, sleep, night wakings, skin temperature, watch wear time and gaps, all measured against the person's own baseline (days t-35 to t-8), plus the known treatment schedule. Self-reports, diary notes and events are used only to make the label, never as inputs. The goal is to warn *before the person says anything*.

## Results on held-out patients

- **Split**: by patient: 60% train, 15% validation, 25% test (750 patients, 14,216 patient-weeks). No patient appears in two splits.
- **Alert threshold**: chosen on the validation patients, never on test. Every method gets the same alert budget: 12% of quiet days.
- **Week metrics**: the forecast made on the last day of each week; the target is a patch onset in the next 7 days.
- **"Caught" and lead time**: an alert counts only if it fires 2 to 7 days before onset.

| Method | Week AUC | Week precision | Week recall | Patches caught 2–7 d early | ER/admissions caught | Median lead (capped at 7) | Alert precision | Alerts / patient / month |
|---|---|---|---|---|---|---|---|---|
| Baseline: steps drop | 0.556 | 9% | 20% | 39% | 52% | 5 d | 8% | 1.25 |
| Baseline: treatment schedule only (same learner) | 0.79 | 18% | 40% | 59% | 42% | 6 d | 14% | 0.67 |
| Logistic, wearable + schedule (comparison) | 0.754 | 12% | 23% | 44% | 57% | 6 d | 14% | 0.63 |
| Radar (gradient boosting, wearable + schedule) | 0.804 | 20% | 44% | 64% | 54% | 6 d | 15% | 0.84 |

How to read it:

- **The treatment calendar is the honest baseline.** Most rough patches fall in the days after a dose, so a model given only the calendar already does well.
- **Wearables add lift on top of the calendar:** +5 points of patches caught early and +13 points of ER/admissions caught, at about the same alert load.
- **Precision is modest:** about 1 alert in 5 is followed by a rough week, against a base rate of about 1 in 18 weeks. That works for "move the call earlier". It does not work for anything clinical.

Signals around an ER visit in the synthetic data: resting heart rate climbs about 3 bpm and steps fall about 850 a day from roughly 8 days before. That is the window the forecaster uses.

### Real-data check (fatigue study, 204 people with a Fitbit)

- On real bad days, steps are lower than the person's own normal: -0.235 SD on bad days vs 0.073 SD on other days, a same-day AUC of about 0.59.
- But a next-day forecast from the previous 2 days of wearable data alone scores **AUC 0.482** (chance). Yesterday's own rating scores 0.64.
- So the lead time is shown on the synthetic data only. On real people the wearable confirms a bad day but does not yet predict one. The deck should say so.

## Self-check against a judging guide

Challenge 3 ships without judging criteria, so we scored ourselves against the Challenge 1 guide's aspects, adapted to this task. The raw numbers are in `GET /api/c3/metrics` (`calibration`, `subgroups`, `lift_vs_schedule_ci95`).

| Aspect | What we did | Where it is weak |
|---|---|---|
| Scientific soundness | The outcome combines how the person feels (feeling ≤2, fatigue ≥3) with clinical events (ER, admission, pause), and one bad day is not a patch. Inputs are only data known by the evening of the forecast: the wearable vs the person's own baseline (days t-35 to t-8), plus the treatment calendar. Labels and events are never inputs. | 55% of daily check-ins are missing, and skips cluster on bad days, so the label under-counts. |
| Validation | Patients the model never saw (750). Thresholds set on separate validation patients. Every method gets the same alert budget. **Lift over the schedule-only model, 95% CI over patients:** patches caught +3 to +8 points; ER/admissions caught +6 to +19 points. **Calibrated:** predicted vs observed 7-day risk agrees in every decile (top decile 21% predicted vs 20% observed). Brier score 0.0476 vs 0.052 for always guessing the base rate. | The lift over the calendar is real but small. Lead time is capped at the 7-day window: the "7" bucket means 7 or more. The calendar baseline has the same median, so lead time is not the wearable's win; the extra patches and ER visits caught are. |
| Clinical insight | Risk peaks in the days after a dose (the chemo low point), climbs with cycle number, and is higher for IV chemo and chemoradiation. Wearable signals add risk on top: broken sleep, rising resting heart rate, lower HRV, fewer steps, rising skin temperature, watch left off. Before an ER visit, resting heart rate rises about 3 bpm and steps fall about 850 a day from roughly 8 days out. These are associations, not causes. | All of this is from made-up data whose patterns were designed in. On the real fatigue study, the wearable confirms a bad day on the day itself but does not predict the next day (AUC 0.482). |
| Fairness | Week-level AUC, recall and precision by age, sex, race and ethnicity, language, cancer type, device and living alone. AUC is 0.74 to 0.88 in every group with enough data. Groups with fewer than 30 rough weeks are marked "too few to judge" rather than reported. | Recall is lower for Haitian Creole speakers (34% vs 51% Spanish), Black patients (38% vs 45% Hispanic) and ovarian cancer (32%). Asian patients, 10 cancer types and "other" race are too small to judge. |
| Reproducibility | A fixed seed, a split by patient, and one command (`npm run build:data`) from the raw download to the served JSON. `npm run e2e` re-checks the live API and saves `runs/e2e-*.json`; `npm run contract` rebuilds CONTRACT.md from that run. | Training takes about 25 s on a laptop. |

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python pandas numpy scikit-learn pyarrow
npm install
npm run build:data        # train.py (about 25 s) + export.py; reads ~/Downloads/Challenge3_Bad_Week_Radar
.venv/bin/python -I analysis/real_check.py ~/Downloads/Challenge3_Bad_Week_Radar && .venv/bin/python -I analysis/export.py
npx tsc --noEmit && npx wrangler deploy   # workers.dev only, no custom domain
npm run e2e               # hits every endpoint, saves runs/e2e-<time>.json and runs/e2e-latest.json
```

Verified by deploying to workers.dev and running the E2E check against it. No dev server was run on this Mac.

## Demo story (2 minutes)

1. **The problem (15 s).** "Coaches hear about a bad week at the next call, days late. This watches the wearable and warns early."
2. **Roster (20 s).** 60 survivors as of the evening of 31 Jan 2025. 8 alert, 8 watch, 44 ok, sorted by risk. None of the 44 "ok" survivors had a rough patch start in the next 7 days.
3. **Open P02836** (52M, lung cancer, alert) (45 s). Over 10 days their risk climbed from 6% to 24%, and it has been over the alert line for the last 4 days. The calendar alone says 24% (mid-chemoradiation), and the wearable confirms it: steps are 34% below their usual. They have *not said anything*: when they checked in they rated their days 4 to 5 out of 5, and they have skipped the last 3 check-ins. Suggested action: check in this week, lower the activity goal, and move the coaching call earlier.
4. **Reveal (15 s).** Click "what happened next". The rough patch started 7 days later, with an ER visit and hospital admission on day 8. The coach had a week's head start.
5. **Contrast (15 s).** Open P02465. The calendar alone says 2%, the wearable says 51%: sleep is broken up (8 wakings a night vs 1) and resting heart rate is up. This is a rough patch the schedule cannot see. It started the next day.
6. **Honesty (15 s).** The metrics table: model vs calendar vs steps rule, same alert budget. Then the real-data caveat.

## Files

- `analysis/train.py`: labels, features, models, held-out evaluation → `analysis/out/metrics.json`
- `analysis/export.py`: caseload, explanations, actions → `src/data/survivors.json`, `src/data/metrics.json`
- `analysis/real_check.py`: fatigue-study check
- `src/index.ts`: Worker · `public/index.html`: demo page · `scripts/e2e.mjs`: E2E check

Data: made-up patients by the Crane Lab, Sylvester Comprehensive Cancer Center. Real data: Rao C, et al., Frontiers in Digital Health 2023 (zenodo 8018238); Yfantidou S, et al., Scientific Data 2022 (zenodo 7229547, CC BY 4.0).
