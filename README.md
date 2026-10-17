# C3 Bad Week Radar

Coach Console module for challenge "The Bad Week Radar" (eMerge hackathon, Healthcare track, Sylvester).
It watches a survivor's own check-ins, their wearable and their treatment calendar. Every evening it forecasts whether a rough patch will start in the next 7 days, explains which signals drove the forecast, and gives the coach a suggested action.

- Live: https://c3-rough-patch.zay-259.workers.dev (demo page) · API under `/api/c3`. See [CONTRACT.md](CONTRACT.md).
- Stack: TypeScript Cloudflare Worker (no LLM step needed). The model is trained offline in Python and its outputs are baked into `src/data/*.json`.

## What counts as a rough patch (and why)

"Rough patch" is not a column in the data, so we define it from what the person and the clinic report, **relative to the person**:

- **Rough day**, any of:
  - **Feeling, against their own normal**: a daily feeling of 1, or 2+ points below their own median of their last 28 check-ins. Until someone has 5 check-ins, a feeling of 2 or less.
  - **Weekly symptoms**: on the weekly check-in, any of fatigue, nausea, pain, appetite loss, diarrhea, trouble sleeping, anxiety or sadness at 3+ (of 4), or 2+ above their own usual.
  - **Clinical event**: an ER visit, hospital admission or treatment pause.
- **Rough patch**: a rough day with another rough day within 3 days, or any clinical event. One bad day is not a patch.
- **Onset**: the first patch day after 7 quiet days. Days already inside a patch are not scored. Being sick already does not count as a hit.

**Why relative to the person:** a "3 out of 5" is a bad day for someone who usually says 5, and a normal day for someone who always says 3. Someone who always rates low does not get a patch every week, and a drop from a high baseline counts.

**Skipped check-ins.** 55% of daily check-ins are missing. We measured what a skip means: on the next check-in a person reports a rough day **4.9%** of the time after no skips, 6.4% after 2, 6.9% after 3 and **8.6% after 5 or more** (about **1.8x**). So skipping is a warning sign. The run of skipped check-ins (and missed coaching calls) is a forecast **input**, so a longer run weighs more. It is not part of the label.

We tested one more step and kept it **out of the label**: on a day with no check-in, use that wearable estimate (a model trained on check-in days, with the skip run as an input) to fill in "rough". Two reasons it stays out:
- The forecaster then no longer beat the treatment calendar (AUC 0.843 vs 0.844), and the ER gain disappeared.
- Patients who skip the most got 1.95 patches each, vs 1.4 for the most engaged. The label was partly measuring disengagement.

Without it, patches are flat across engagement (1.0 / 1.01 / 1.05 / 0.96 per patient from the most to the least engaged quarter). Turn it back on with `C3_PROXY=1`. Reproduce the old label with `C3_LABEL=v1`.

**Cross-check, so the new label is not grading itself.** Measured on the wearable + calendar model, before check-ins became inputs, at a 12% alert budget on the same test patients:
- On the new label's onsets, the model trained on the new label scores week AUC 0.819 with 66% recall. The model trained on v1 scores 0.815 and 69%, but sends more alerts (0.84 vs 0.78 per patient per month).
- On v1 onsets, the v1-trained model is slightly better (0.804 vs 0.799).

So the two are at parity. The new label is served because it is the better definition, not because it scores higher. **Its numbers are not comparable with the v1 numbers in older runs.**

**Inputs, all known by the evening of the forecast:**
- **The person's own check-ins**, against their usual: last feeling, its gap from their median, rough days reported in the last 2 weeks, worst weekly symptom and its gap from their usual. **Ratings are used only up to 3 days back** (see below).
- **Engagement**: the run of skipped daily check-ins, the check-in rate over 14 days, and coaching calls missed, moved or completed. These are used up to today.
- **Wearable**: steps, active minutes, resting heart rate, HRV, sleep, night wakings, skin temperature, watch wear time and gaps, each against the person's own baseline (days t-35 to t-8).
- **The known treatment schedule.**

Events and diary text are never inputs.

**Why ratings lag 3 days.** Scored days exclude days already inside a patch, and a patch day is a rough day with another within 3 days. On a scored day, a rough rating in the last 3 days would therefore reveal that the next 3 days are calm. That is a leak, so ratings are used only up to t-3. Skips are used up to today, because a skip is never a rough day. A deployed version with a causal scoring mask could use yesterday's rating, which on the real fatigue study is the strongest next-day signal (AUC 0.64 vs 0.48 for the wearable).

## Results on held-out patients

- **Split**: by patient: 60% train, 15% validation, 25% test (750 patients, 14,501 patient-weeks). No patient appears in two splits.
- **Alert threshold**: chosen on the validation patients, never on test. Every method gets the same alert budget, **5% of quiet days**. That budget comes from coach capacity, and was set before comparing models: on a 60-person caseload it is about one new alert per coach per day. **Watch** is the broader 12% line.
- **Model choice**: the check-in model was picked on validation patients (it won at both the 5% and 12% budgets there), then scored once on test.
- **Week metrics**: the forecast made on the last day of each week; the target is a patch onset in the next 7 days.
- **"Caught" and lead time**: an alert counts only if it fires 2 to 7 days before onset.

| Method | Week AUC | Week precision | Week recall | Patches caught 2–7 d early | ER/admissions caught | Median lead (capped at 7) | Alert precision | Alerts / patient / month |
|---|---|---|---|---|---|---|---|---|
| Baseline: steps drop | 0.567 | 10% | 10% | 25% | 27% | 5 d | 8% | 0.66 |
| Baseline: treatment schedule only (same learner) | 0.808 | 20% | 26% | 36% | 22% | 7 d | 11% | 0.36 |
| Logistic, wearable + schedule (comparison) | 0.768 | 16% | 14% | 25% | 33% | 6 d | 13% | 0.33 |
| Same learner, wearable + schedule (no check-ins) | 0.819 | 22% | 24% | 41% | 30% | 5 d | 17% | 0.45 |
| **Radar (gradient boosting, check-ins + wearable + schedule)** | **0.827** | **23%** | **28%** | **48%** | **36%** | **6 d** | **18%** | **0.48** |

How to read it:

- **The treatment calendar is the honest baseline.** Most rough patches fall in the days after a dose, so a model given only the calendar already does well on AUC.
- **At a budget a coach can act on, the Radar clearly beats the calendar.**
  - Patches caught early: 48% vs 36% (95% CI +8 to +15 points over patients).
  - ER/admissions caught early: 36% vs 22% (CI +9 to +20).
  - Alert precision: 18% vs 11%.
- **What the check-ins add over wearable + calendar:** +3 to +9 points of patches caught (CI), and +1 to +12 points of ER/admissions.
- **It is still a nudge, not a diagnosis.**
  - About 1 alert in 5.5 is followed by a rough patch within a week, against a base rate of about 1 in 21 weeks.
  - At this budget it catches about half of rough patches. The watch line (12%) catches 70%, at lower precision.
  - It is good enough for "message them" or "move the call earlier", and not for anything clinical.

**What we tried that did not help (scored on validation, then test):**
- **Alerting on the surprise only** (risk above the calendar's): worse on both precision and recall. The calendar part is part of the signal, not noise.
- **A daily top-5 call list per 60-person caseload:** about 8% of listed patients start a patch within a week, vs a 4.7% base rate. Being on the list at some point in the week "reaches" 90% of patches, but the calendar alone reaches 88%, because 35 slots a week touch nearly everyone. Not a useful measure.
- **Target missed:** we aimed for 25%+ alert precision. The best we reached is 18% alert precision and 23% week precision. The synthetic rough patches are noisy, and 55% of check-ins are missing.

Signals around an ER visit in the synthetic data: resting heart rate climbs about 3 bpm and steps fall about 850 a day from roughly 8 days before. That is the window the forecaster uses.

### Urgent tier: ER visit or hospital admission

A separate model predicts an ER visit or hospital admission in the next 7 days. It uses the wearable and calendar inputs (not the check-ins), and is trained on days with no ER visit in the past week. It flags the top 3% of days as **urgent**. That is a separate signal: an urgent survivor is always on alert, sorts first, and gets a "call today" action. The rough-patch alert is unchanged, so the urgent tier costs it nothing.

| On held-out patients (182 ER/admissions) | ER caught 2–7 d early | Median lead | Flag precision | Flags / patient / month | AUC | Avg precision |
|---|---|---|---|---|---|---|
| Urgent head (wearable + schedule) | 47% | 4 d | 7.4% | 0.38 | 0.859 | 0.064 |
| Urgent head, schedule only | 36% | 5 d | 6.9% | 0.23 | 0.845 | 0.0486 |
| Rough-patch Radar, same 3% budget | 29% | 6 d | 6.1% | 0.27 | 0.788 | 0.0362 |

The base rate is 1.2% of days, so an urgent flag carries about 6x the usual risk. That is enough for a "call today" check-in, and not enough for anything clinical.

### Real-data check (fatigue study, 204 people with a Fitbit)

- On real bad days, steps are lower than the person's own normal: -0.235 SD on bad days vs 0.073 SD on other days, a same-day AUC of about 0.59.
- But a next-day forecast from the previous 2 days of wearable data alone scores **AUC 0.482** (chance). Yesterday's own rating scores 0.64.
- So the lead time is shown on the synthetic data only. On real people the wearable confirms a bad day but does not yet predict one. The deck should say so.

## Self-check against a judging guide

Challenge 3 ships without judging criteria, so we scored ourselves against the Challenge 1 guide's aspects, adapted to this task. The raw numbers are in `GET /api/c3/metrics` (`calibration`, `subgroups`, `lift_vs_schedule_ci95`).

| Aspect | What we did | Where it is weak |
|---|---|---|
| Scientific soundness | The outcome is relative to the person: feeling against their own median, 8 weekly symptoms against their own usual, plus clinical events (ER, admission, pause). One bad day is not a patch. A cross-check against the old label shows the new one does not grade itself. Inputs are only data known by the evening of the forecast: the person's check-ins (ratings lagged 3 days to avoid a leak through the scoring mask), skips and missed calls, the wearable vs their own baseline, and the treatment calendar. Events and diary text are never inputs. | 55% of daily check-ins are missing. Skips predict rough days (1.8x after 5), but filling them in from the wearable made the label track disengagement, so missed days stay unlabelled and the label still under-counts. |
| Validation | Patients the model never saw (750). Thresholds set on separate validation patients. Every method gets the same alert budget. **Lift over the schedule-only model, 95% CI over patients:** patches caught +8 to +15 points; ER/admissions caught +9 to +20 points, at a 5% alert budget. **Calibrated:** predicted vs observed 7-day risk agrees in every decile (top decile 19% predicted vs 19% observed). Brier score 0.0407 vs 0.0445 for always guessing the base rate. | The lift over the calendar is real but small. Lead time is capped at the 7-day window: the "7" bucket means 7 or more. The calendar baseline has the same median, so lead time is not the wearable's win; the extra patches and ER visits caught are. |
| Clinical insight | Risk peaks in the days after a dose (the chemo low point), climbs with cycle number, and is higher for IV chemo and chemoradiation. Wearable signals add risk on top: broken sleep, rising resting heart rate, lower HRV, fewer steps, rising skin temperature, watch left off. Before an ER visit, resting heart rate rises about 3 bpm and steps fall about 850 a day from roughly 8 days out. These are associations, not causes. | All of this is from made-up data whose patterns were designed in. On the real fatigue study, the wearable confirms a bad day on the day itself but does not predict the next day (AUC 0.482). |
| Fairness | Week-level AUC, recall and precision by age, sex, race and ethnicity, language, cancer type, device and living alone. AUC is 0.76 to 0.85 in every cancer type and group with enough data. Groups with fewer than 30 rough weeks are marked "too few to judge" rather than reported. | Recall at the 5% budget is lower for Haitian Creole speakers (22% vs 31% Spanish), breast cancer (21%) and sarcoma (13%), and for Black patients (26% vs 29% Hispanic). Asian patients, 10 cancer types and "other" race are too small to judge. |
| Reproducibility | A fixed seed, a split by patient, and one command (`npm run build:data`) from the raw download to the served JSON. `npm run e2e` re-checks the live API and saves `runs/e2e-*.json`; `npm run contract` rebuilds CONTRACT.md from that run. | Training takes about 3 minutes on a laptop (it also trains the v1 cross-check model and the check-in nowcast). |

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python pandas numpy scikit-learn pyarrow
npm install
npm run build:data        # train.py (about 3 min) + export.py; reads ~/Downloads/Challenge3_Bad_Week_Radar
.venv/bin/python -I analysis/real_check.py ~/Downloads/Challenge3_Bad_Week_Radar && .venv/bin/python -I analysis/export.py
npx tsc --noEmit && npx wrangler deploy   # workers.dev only, no custom domain
npm run e2e               # hits every endpoint, saves runs/e2e-<time>.json and runs/e2e-latest.json
```

Verified by deploying to workers.dev and running the E2E check against it. No dev server was run on this Mac.

## Demo story (2 minutes)

1. **The problem (15 s).** "Coaches hear about a bad week at the next call, days late. This watches the wearable and warns early."
2. **Roster (20 s).** 60 survivors as of the evening of 31 Jan 2025: 5 alert (2 of them urgent), 4 watch, 51 ok, sorted by risk. Of the 51 "ok" survivors, 1 had a rough patch start in the next 7 days.
3. **Open P02836** (52M, lung cancer, alert) (45 s). Risk 34% against an alert line of 16%. The calendar alone says 25% (mid-chemoradiation), and the headline says why it is higher: **they have gone quiet**. Their last rating was their usual 5/5, then they skipped the last 3 check-ins. Their check-ins add 10 points of risk, and steps are 34% below their usual. Suggested action: a short, no-pressure message, and move the coaching call earlier.
4. **Reveal (15 s).** Click "what happened next". The rough patch started 7 days later, with an ER visit and hospital admission on day 8. The coach had a week's head start.
5. **Contrast (15 s).** Open P02465. The calendar alone says 2%, the Radar says 51%: sleep is broken up (8 wakings a night vs 1), steps are down 64%, and the watch was off 2 of the last 7 days. This is a rough patch the schedule cannot see. It started the next day.
6. **Urgent (15 s).** The two red "urgent" survivors at the top have an ER-level risk 5 to 9 times the usual. For P03000, treatment was paused 6 days later. Neither went to the ER in the next 7 days, though: urgent flags are right about 1 time in 13. It is a reason to call, not a diagnosis.
7. **Honesty (15 s).** The metrics table: model vs calendar vs steps rule, same alert budget. Then the real-data caveat.

## Files

- `analysis/train.py`: labels, features, models, held-out evaluation → `analysis/out/metrics.json`
- `analysis/export.py`: caseload, explanations, actions → `src/data/survivors.json`, `src/data/metrics.json`
- `analysis/real_check.py`: fatigue-study check
- `src/index.ts`: Worker · `public/index.html`: demo page · `scripts/e2e.mjs`: E2E check

Data: made-up patients by the Crane Lab, Sylvester Comprehensive Cancer Center. Real data: Rao C, et al., Frontiers in Digital Health 2023 (zenodo 8018238); Yfantidou S, et al., Scientific Data 2022 (zenodo 7229547, CC BY 4.0).
