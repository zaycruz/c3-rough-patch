# Methodology — C3 Bad Week Radar (rough-patch forecaster and urgent tier)

The C3 module is for coaches. Each evening it gives every survivor a risk score. The score says how likely a rough patch is to start in the next 7 days. A second, separate model flags an **urgent** risk of an ER visit or hospital admission in the next 7 days. Two rule-based checks add same-day "call today" reasons: a diary-note red-flag scan and a model-free escalation. The models are trained offline in Python. Their outputs are baked into `src/data/*.json` and a Cloudflare Worker (`src/index.ts`) serves them. The module has no generative AI step. `README.md` says "no LLM step needed". All coach-facing text comes from fixed templates in `analysis/export.py` (`describe`, `describe_checkins`, `actions`, `social_needs`).

All data used for training and testing is synthetic. The only real data is the fatigue study, and it is used for one check (section A8).

**Where the numbers live**

- `README.md`: the headline tables and the honest limits.
- `REPRODUCE.md`: maps each README number to its file and key, and gives the platform tolerance.
- `analysis/out/metrics.json`: rough-patch model, baselines, calibration, subgroups, bootstrap CIs, urgent head (written by `analysis/train.py`).
- `analysis/out/urgent_ci.json`: CIs for the urgent tier and the note scan, plus results by language.
- `analysis/out/notes_scan.json`, `analysis/out/escalation.json`: the rule-based checks.
- `analysis/out/real_check.json`: real-data check on the fatigue study.
- `analysis/out/exp_temporal_holdout.json`, `analysis/out/exp_notes_features.json`, `analysis/out/er_presignal.json`: experiments.
- `analysis/out/historical/*.json`: older pipeline runs (proxy label, label v2 before check-ins, worklist on validation). `label_crosscheck.json` and `exp_checkin_worklist_test.json` are not committed. The full `scripts/reproduce.sh` run writes them, and `REPRODUCE.md` names them as the source.
- `analysis/research_log.md`: every model-search experiment, with what was picked on validation and what was scored on test.
- `src/data/metrics.json`: the served metrics (headline, fairness blocks).
- `runs/reproduce-*.md`: one-command reproduce logs. `runs/e2e-latest.json`, `runs/page-check-latest.json`: checks against the live Worker.

---

## A. Rough-patch forecaster (gradient boosting)

### A1. Question and target

Question: will a rough patch **start** in the next 7 days for this person?

The data has no "rough patch" column, so the label is built from what the person and the clinic report, **relative to the person** (`analysis/train.py`, `label_v2` and `episodes`):

- **Rough day**, any of:
  - Daily feeling of 1, or 2+ points below the person's own median of their last 28 check-ins. Until the person has 5 check-ins, a feeling of 2 or less.
  - On the weekly check-in, any of 8 symptoms (fatigue, nausea, pain, appetite loss, diarrhea, trouble sleeping, anxiety, sadness) at 3+ of 4, or 2+ above the person's own usual.
  - A clinical event: ER visit, hospital admission or treatment pause.
- **Rough patch day**: a rough day with another rough day within 3 days, or any clinical event. One bad day is not a patch.
- **Onset**: the first patch day after 7 quiet days.
- **Target at day t**: an onset on day t+1 to t+7 (`HORIZON = 7`).

The unit is the **person-day**. A forecast is made each evening for each person-day. Days already inside a patch (`in_episode`) and the first 14 program days are not scored. Being sick already does not count as a hit.

Two evaluation views:
- **Week metrics** (`week_metrics`): the forecast on the last day of each patient-week. The target is an onset in the next 7 days.
- **Episode metrics** (`episode_metrics`): an onset is "caught" only if an alert fires 2 to 7 days before it (`MIN_LEAD = 2`). Lead time is onset minus the first alert day, capped by the 7-day window. Alert precision counts alert runs (first alert day after 3 quiet days) that are followed by a patch within 7 days.

Skipped check-ins are **not** part of the label. A wearable "proxy" that fills in rough days on skipped days was tested and kept out. Reasons (`README.md`):
- With the proxy, the forecaster no longer beat the calendar (week AUC 0.843 vs 0.844).
- With the proxy, the least engaged patients got 1.95 patches each, vs 1.4 for the most engaged. The label was partly measuring disengagement.
- Without it, patches are flat across engagement quarters: 1.0 / 1.01 / 1.05 / 0.96 per patient.

`C3_PROXY=1` turns the proxy back on. `C3_LABEL=v1` gives the old label (feeling ≤ 2, weekly fatigue ≥ 3, or a clinical event; `label`).

**Label cross-check, so the new label does not grade itself.** This ran on the earlier wearable + calendar model, before check-ins became inputs, at a 12% alert budget on the same test patients (`analysis/exp/label_crosscheck.py`, `train.py @ d72545d`):
- On the new label's onsets: the model trained on the new label scores week AUC 0.819 and 66% recall. The model trained on v1 scores 0.815 and 69%, but sends more alerts (0.84 vs 0.78 per patient per month).
- On v1 onsets, the v1-trained model is slightly better (0.804 vs 0.799).
- The README calls this parity. It serves the new label "because it is the better definition, not because it scores higher". Numbers under the new label are not comparable with v1 numbers in older runs.

Source: `README.md`, `analysis/train.py`, `analysis/out/historical/metrics_v2_proxy.json`, `analysis/out/historical/metrics_v2_noproxy.json`, and `analysis/out/historical/label_crosscheck.json` (written by the full reproduce run; not committed).

### A2. Data

- **Source**: the sponsor bundle `Challenge3_Bad_Week_Radar` (Crane Lab, Sylvester Comprehensive Cancer Center). Made-up patients.
  - `synthetic_data/synthetic_daily.csv`: 465,466 rows, one per person-day.
  - `synthetic_data/synthetic_patients.csv`: 3,000 people.
- **Real**: none in training or test. The real fatigue study is used only for the check in A8.
- **Test set**: 750 patients and 14,501 patient-weeks. 721 onsets are scored by the episode metric (`methods.model.episodes.episodes`).
- **Missing data**: 55% of daily check-ins are missing. Skips predict rough days. The rate of a rough day at the next check-in is 4.9% after no skips, 6.4% after 2, 6.9% after 3 and 8.6% after 5 or more (about 1.8x).
- **Exclusions from scoring**: days inside a patch, and program days before 14.
- Files are checked by sha256 before any step runs (`scripts/reproduce.sh`; hashes in `data/README.md`).
- C3 uses no other public dataset: no MEPS, NHANES, CGMacros or AnnoMI (`data/README.md`).

Source: `data/README.md`, `README.md`, `analysis/out/metrics.json` (`counts`, `label_v2.rough_rate_after_skips`, `methods.model`).

### A3. Features

All inputs are known by the evening of the forecast (`analysis/train.py`, `features`, `checkin_features`):

| Group | What | Leakage control |
|---|---|---|
| Wearable (`SIGNALS`) | steps, active minutes, resting heart rate, HRV, sleep minutes, sleep efficiency, night wakings, skin temperature, watch wear time. 3-day and 7-day means as z-scores vs the person's own baseline; skin temperature 3-day max; watch-off days and low-wear days in the last 7. | Personal baseline is days t-35 to t-8 (`shift(8)`, 28-day rolling median and SD). The last week is left out, so a slow slide still shows. |
| Check-in values (`CHECKINS`) | last feeling, its gap from the person's median, 7-day mean gap, rough self-reports in 14 days, worst weekly symptom and its gap from the person's usual. | **Lagged 3 days** (`CHECKIN_LAG = 3`). Personal medians use past reports only (`_personal_base`). |
| Engagement | run of skipped daily check-ins, check-in rate over 14 days, coaching calls missed or rescheduled (28 days), calls completed (14 days). | Used up to today. A skip is never a rough day. |
| Treatment calendar (`SCHEDULE`) | on treatment, cyclic plan, days since dose, days 1–6 after a dose, dose soon, cycle number, radiation, IV chemo, day in program. | Known schedule. |

**Why ratings lag 3 days.** Scored days exclude days inside a patch. A patch day is a rough day with another within 3 days. So on a scored day, a rough rating in the last 3 days would reveal that the next 3 days are calm. That is a leak. Ratings are therefore used only up to t-3. A deployed version with a causal scoring mask could use yesterday's rating (`README.md`).

**Never inputs**: the events column and diary text. Diary notes were tested as inputs under the same 3-day lag and failed a rule fixed beforehand (see C1).

Source: `README.md`, `analysis/train.py`.

### A4. Split

- **By patient**, with a fixed seed (`SEED = 7`): 60% train, 15% validation, 25% test (`main`). No patient appears in two splits. Test has 750 patients.
- **Train** patients fit the models. **Validation** patients set the alert thresholds. **Test** patients produce every reported number.
- **Temporal holdout** (`analysis/exp/temporal_holdout.py`; design fixed before running, "Report whatever it shows"):
  - Train: train and validation patients, dates before 2025-06-24 (a 7-day gap before 2025-07-01, so no training label sees past it).
  - Alert line: validation patients, 2025-07-01 to 2025-09-24, 5% of quiet days.
  - Test: test patients, dates from 2025-10-01. Later dates and unseen patients: 244 patients, 147 patches.
  - Stated limit: the rough-day nowcast inside label v2 was fit on train patients over all dates. The proxy that uses it is off in the served label.

**How tuning was protected, and where it was not.**
- Alert thresholds were always set on validation patients, never on test.
- The served check-in model was picked on validation patients. It won at both the 5% and 12% budgets there. It was then scored on test (`README.md`; `analysis/research_log.md`, 2026-10-17 entry).
- The notes-as-inputs rule (C1) and the escalation check-in rule (C2) were fixed before running and decided on validation.
- The alert budget: `README.md` and the code comment in `main` say the 5% budget comes from coach capacity and "was set before comparing models". The research log's 2026-10-17 entry also records that the budget "moved to 5%" in that round. The older label cross-check ran at a 12% budget.
- Test patients were scored in **more than one** research round. The research log records one test run per round:
  - A feature round: the validation gains "mostly did **not** transfer" to test, and nothing was merged.
  - A model-family round for the ER task: an ensemble ranked slightly better on test (AUC 0.863 vs 0.858) but caught fewer ER events (43% vs 47%). It was not adopted.
  - The check-in round (above).
- The decision to keep the wearable proxy out of the label used test-split numbers (`metrics_v2_proxy.json`, week AUC 0.843 vs 0.844) as one of its two reasons. The other reason was the engagement bias.
- There is no nested cross-validation and only one patient-split seed. Repeated seeds are Future work.

Source: `README.md`, `analysis/research_log.md`, `analysis/train.py`, `analysis/exp/temporal_holdout.py`, `analysis/out/exp_temporal_holdout.json`.

### A5. Model and selection

- **Served model**: scikit-learn `HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)` on check-ins + wearable + calendar (`main`, `gb`). It is fit on train patients, on scored days only.
- **Hyperparameters** are fixed. The research log tried other settings (more iterations, smaller learning rates, leaf limits, class weights). They were "within noise" and not adopted.
- **Model families** (branch `research/model-v2`, not in `reproduce.sh`): LightGBM, XGBoost, random forest, ExtraTrees, spline logistic, a 1D-CNN and ensembles. On validation none beat HistGB on rough patches. HistGB is served for both heads.
- **Feature sets**: trend, previous-cycle, phase, engagement, interaction and history features were tried. The log's outcome is "nothing merged". The 2026-10-17 round added the check-in features. On validation at the 5% budget they raised alert precision (0.165 vs 0.161) and patch recall (0.503 vs 0.460).
- **Calibration**: there is **no recalibration step**. The served risk is the raw HGB probability. Calibration is measured on test (A7).
- **Explanations**: `analysis/export.py` (`drivers`) sets one signal group back to the person's normal and reports how much the risk drops. `train.py` also stores permutation importance on test (`feature_importance_auc_drop`). The top three are `on_treatment` 0.1246, `iv_chemo` 0.1094 and `days_since_dose` 0.0339. The sources contain no measured check of how faithful the counterfactual explanations are.

Source: `analysis/train.py`, `analysis/research_log.md`, `REPRODUCE.md` (section 4), `analysis/out/metrics.json` (`feature_importance_auc_drop`).

### A6. Baseline

**One baseline per outcome.** For rough patches it is the **calendar-only rough-patch model**: the same learner and settings, fit only on the treatment calendar features (`SCHEDULE`; `score_schedule` in `main`).

Every method gets the **same alert budget: 5% of quiet validation days**. On a 60-person caseload that is about one new alert per coach per day. **Watch** is the broader 12% line. Comparisons in the table:
- a steps-drop rule (`score_steps_rule`);
- a logistic regression on wearable + calendar (`fit_lr`);
- the same learner on wearable + calendar without check-ins (`score_wearable`).

The README calls the calendar the honest baseline: most rough patches fall in the days after a dose, so a calendar-only model already does well on AUC.

Source: `README.md`, `analysis/train.py`.

### A7. Metrics with 95% CIs

Held-out test patients, 5% alert budget (`README.md`; keys in `analysis/out/metrics.json` → `methods.*`, `ablation_without_checkins`):

| Method | Week AUC | Week precision | Week recall | Patches caught 2–7 d early | Median lead (capped at 7) | Alert precision | Alerts / patient / month |
|---|---|---|---|---|---|---|---|
| Baseline: steps drop | 0.567 | 10% | 10% | 25% | 5 d | 8% | 0.66 |
| **Baseline: calendar-only rough-patch model** | 0.808 | 20% | 26% | 36% | 7 d | 11% | 0.36 |
| Logistic, wearable + schedule | 0.768 | 16% | 14% | 25% | 6 d | 13% | 0.33 |
| Same learner, wearable + schedule (no check-ins) | 0.819 | 22% | 24% | 41% | 5 d | 17% | 0.45 |
| **Radar (check-ins + wearable + schedule)** | **0.827** | **23%** | **28%** | **48%** | **6 d** | **18%** | **0.48** |

**How the CIs are computed** (`bootstrap_lift`): a **paired** patient bootstrap. Each of 1,000 resamples draws held-out patients with replacement and recomputes both methods on the same patients. The CI is the 2.5th to 97.5th percentile of the difference. Seed 7.

| Comparison | Metric | 95% CI | Significant? |
|---|---|---|---|
| Radar vs calendar-only model | patches caught 2–7 d early (48% vs 36%) | +8 to +15 points | Yes, CI excludes zero |
| Check-ins added to wearable + calendar | patches caught | +3 to +9 points | Yes, CI excludes zero |
| Temporal holdout: Radar vs calendar | patches caught (44% vs 36%) | -1 to +17 points | **No.** "The lift points the same way but is not significant on this smaller, later sample." |

Temporal holdout week AUC: 0.852 vs 0.843 for the calendar.

No CI is reported for the week AUC differences.

**Calibration** (`calibration`; risk deciles over scored test days), in the README's words: "predicted vs observed 7-day risk is within 0.7 points in every decile (top decile 19% predicted vs 19% observed); the lowest deciles are off in relative terms (3rd decile 0.5% predicted vs 0.3% observed). Brier score 0.0407 vs 0.0445 for always guessing the base rate." The calendar-only model has Brier 0.0414 (`calibration.schedule.brier`). Calibration was measured only on the random patient split, not on the temporal holdout (Future work).

**What the numbers mean in practice** (`README.md`):
- About 1 alert in 5.5 is followed by a rough patch within a week. The base rate is about 1 in 21 weeks.
- At this budget the Radar catches about half of rough patches. The watch line (12%) catches 70%, at lower precision.
- The calendar baseline has the same median lead, so lead time is not the wearable's win. The extra patches caught are.

Source: `README.md`, `analysis/out/metrics.json` (`lift_vs_schedule_ci95`, `ablation_without_checkins.lift_of_checkins_ci95`, `calibration`), `analysis/out/exp_temporal_holdout.json`.

### A8. Robustness and falsification

**Real-data check: fatigue study** (`analysis/real_check.py`; Rao C, et al., Frontiers in Digital Health 2023, zenodo 8018238). The file has 9,317 rows. After dropping rows without steps or a bad-day rating, 204 people with a Fitbit and 5,236 days remain.
- This check does **not** run the Radar. It uses 7 Fitbit signals from that study, each as a z-score against the person's median and SD **over all their days** (not past days only).
- Same day: on real bad days, steps are lower than the person's normal: -0.235 SD on bad days vs 0.073 SD on other days.
- Next day: a balanced logistic regression on the mean of the previous 2 days of wearable z-scores, with 5-fold leave-people-out CV (`GroupKFold`), scores **AUC 0.482** (chance).
- Yesterday's own rating, used directly as a score, gets AUC 0.64.
- Conclusion in the README: "the lead time is shown on the synthetic data only. On real people the wearable confirms a bad day but does not yet predict one."

**Falsification and negative results** (`README.md`, `analysis/research_log.md`):
- Alerting on the "surprise" only (risk above the calendar's) was worse on both precision and recall.
- A daily top-5 call list per 60-person caseload: about 8% of listed patients start a patch within a week, vs a 4.7% base rate. The list "reaches" 90% of patches, but the calendar alone reaches 88%. The README calls this "not a useful measure" (`analysis/out/historical/exp_checkin_worklist_test.json`, written by the full reproduce run; not committed).
- The label cross-check and the proxy-label test (A1).

**ER pre-signal** in the synthetic data (`analysis/exp/er_presignal.py`, against the person's median on days -35 to -15): over the last week before an ER visit, resting heart rate averages +1.9 bpm and steps -670 a day. The day before, it is +4.2 bpm and -2,300 steps. These are associations in made-up data whose patterns were designed in.

**Subgroups and fairness** (`subgroups`, served as `fairness` by `export.py` `fairness_block`):
- Metrics are week-level AUC, recall and precision at the alert line, by age group, sex, race and ethnicity, language, cancer type, device and living alone.
- The recall CI comes from a patient bootstrap within each group: 500 resamples, not paired.
- Groups with fewer than 30 rough weeks are marked "too few to judge".
- AUC is 0.76 to 0.85 in every cancer type and group with enough data.
- Only sarcoma is clearly below the overall 28% recall: 13%, CI 0–26%.
- Haitian Creole speakers (22%, CI 10–36%) and breast cancer (21%, CI 14–28%) are lower, but their CIs still reach the overall. The README says there are too few patients to be sure.
- Asian patients, 10 cancer types and "other" race are too small to judge.
- Survivors who prefer Spanish or Haitian Creole, or who live alone, and who are flagged, get a social-needs coach action (`social_needs`).

Source: `README.md`, `analysis/out/real_check.json`, `data/README.md`, `analysis/out/er_presignal.json`, `src/data/metrics.json` (`fairness`).

### A9. Limits

Copied from `README.md`:
- **Lead time is shown on synthetic data only.** On real people the wearable did not predict the next day (AUC 0.482).
- All clinical patterns come from made-up data whose patterns were designed in.
- The lift over the calendar is real but small.
- The 25%+ alert precision target was **missed**. The best reached is 18% alert precision and 23% week precision. "The synthetic rough patches are noisy, and 55% of check-ins are missing."
- Missed days stay unlabelled, so the label still under-counts.
- Lead time is capped at the 7-day window: the "7" bucket means 7 or more.
- The temporal-holdout lift is not significant (CI -1 to +17).
- "It is still a nudge, not a diagnosis." It is good enough for "message them" or "move the call earlier", and not for anything clinical.
- Only sarcoma is clearly below overall recall. Creole speakers and breast cancer are lower but uncertain.
- From this method review: one patient-split seed, no nested CV, no recalibration, and test patients were scored in several research rounds (A4).

### A10. Reproduce

See `REPRODUCE.md`.

```bash
scripts/reproduce.sh data/Challenge3_Bad_Week_Radar         # full
scripts/reproduce.sh data/Challenge3_Bad_Week_Radar quick   # served pipeline only
```

- **Environment**: uv installs Python 3.14 (`.python-version`) and the locked packages (`uv.lock`). CPU only, about 6 GB of RAM. The latest log records Python 3.14.7, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1 and pyarrow 26.0.0.
- **Seed**: `SEED = 7` in `analysis/train.py` and in each script.
- **Number check**: `scripts/check_numbers.py` compares every README number with the run, using `analysis/expected.json`. The script exits non-zero on any mismatch.
- **Fresh-clone proof on Cloudflare** (`scripts/repro-cloudflare.sh`): `runs/reproduce-2026-10-17T18-42-45Z.md`, at commit 96f4259. Result: "**170/170 match**, 0 mismatch, 0 missing; 26 of the matches are within the cross-platform tolerance". Between 96f4259 and the current HEAD (96a8709), only `README.md` and the run logs changed.
- **Platform tolerance**: the numbers were made on macOS arm64. On Linux x86_64 the rough-patch, fairness and real-data numbers match exactly. The urgent ER head and everything built on it can move by up to 2 points. For example, urgent ER caught is 49% instead of 47%, and its CI is +4 to +21 instead of +2 to +19 (`REPRODUCE.md`, "Platform tolerance").
- **Live API**: `npm run e2e` writes `runs/e2e-latest.json` (passed, 2026-10-17T18:29:15.788Z). `runs/page-check-latest.json` also passed.
- **Provenance**: every API response carries `x-c3-run` and `x-c3-commit` headers. `GET /api/c3/metrics` → `provenance` gives the sponsor file hashes, the model file hash and the commit (`export.py`, `provenance`).

---

## B. Urgent tier: ER visit or hospital admission (gradient boosting)

### B1. Question and target

Question: will this person have an ER visit or hospital admission in the next 7 days?

Target `er_ahead`: an ER visit or admission on day t+1 to t+7 (`label`). An event counts if it is the first in 7 days and on program day 14 or later. It is "caught" if a flag fires 2 to 7 days before it (`urgent_metrics`). The unit is the person-day.

Source: `analysis/train.py`, `analysis/urgent_ci.py`.

### B2. Data

The same synthetic data and patient split as A2. The test set has 182 ER visits and admissions. The base rate is 1.2% of scored days.

Source: `README.md`, `analysis/out/metrics.json` (`urgent.methods.urgent.er_events`, `urgent.methods.urgent.base_rate`).

### B3. Features

Wearable + treatment calendar (`wear_feats`). **No check-ins.** The leakage controls are the same as A3. Training and scoring use only days with no ER visit in the past 7 days (`er_recent == 0`) and program day 14 or later.

Source: `README.md`, `analysis/train.py` (`main`).

### B4. Split

The same patient split as A4. The model is fit on train patients. The threshold puts the top 3% of validation days on urgent (`URGENT_RATE = 0.03`). It is never set on test. The model family for this head was compared on validation, then the candidates were scored once on test. The ensemble that ranked better on test AUC was **not** adopted, because it caught fewer ER events (A4). No temporal holdout was run for the urgent head.

Source: `analysis/train.py`, `analysis/research_log.md`.

### B5. Model and selection

`HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)` (`gu` in `main`). It is a separate signal: an urgent survivor is always on alert, sorts first, and gets a "call today" action. The rough-patch alert does not change, so the urgent tier costs it nothing. There is no recalibration step.

Source: `README.md`, `analysis/train.py`.

### B6. Baseline

The **calendar-only ER model**: the same learner, fit only on calendar features (`gus`, `score_urgent_schedule`), at the same 3% budget. For comparison only, the rough-patch Radar is also scored at the same 3% budget.

Source: `README.md`, `analysis/urgent_ci.py`.

### B7. Metrics with 95% CIs

| Held-out patients (182 ER/admissions) | ER caught 2–7 d early | Median lead | Flag precision | Flags / patient / month | AUC | Avg precision |
|---|---|---|---|---|---|---|
| Urgent head (wearable + schedule) | 47% | 4 d | 7.4% | 0.38 | 0.859 | 0.064 |
| **Baseline: calendar-only ER model** | 36% | 5 d | 6.9% | 0.23 | 0.845 | 0.0486 |
| Rough-patch Radar at the same 3% budget | 29% | 6 d | 6.1% | 0.27 | 0.788 | 0.0362 |

- **CI method** (`analysis/urgent_ci.py`, `boot`): a paired patient bootstrap with 1,000 resamples and seed 7. The CI is the 2.5th to 97.5th percentile of the recall difference.
- **Lift over the calendar-only ER model**: 47% vs 36%, 95% CI **+2 to +19 points**. The CI excludes zero, so the lift is significant. On Linux, the result is 49% and CI +4 to +21.
- **What a flag means**: about 6x the usual risk. About 1 in 14 urgent flags is followed by an ER visit or admission within 7 days. The coach sees: "about 6x the usual ER or hospital risk this week. A prompt to check in, not a prediction".
- **Calibration**: the README makes no calibration claim for this head. `metrics.json` → `urgent.calibration` gives Brier 0.0115 vs 0.0117 for the base rate. In the middle deciles the model predicts less risk than was observed (for example 0.0103 predicted vs 0.0179 observed). Do not read the urgent risk as a calibrated probability.

Source: `README.md`, `analysis/out/metrics.json` (`urgent`), `analysis/out/urgent_ci.json`, `src/data/metrics.json` (`headline.urgent.timesUsualRisk`), `REPRODUCE.md`.

### B8. Robustness

By language (ER caught 2–7 d early, calendar → urgent): English 36% → 51%, Spanish 32% → 40%, Haitian Creole 50% → 44%. Creole has 18 ER events. One event moves the Creole result 6 points, so the README calls the dip "noise, not a finding". No real-data check exists for ER outcomes. The public studies found have no clinical events.

Source: `README.md`, `analysis/out/urgent_ci.json` (`by_language`).

### B9. Limits

- The flag "is not a prediction". It is enough for a "call today" check-in, and not for anything clinical.
- It was tested on synthetic data only.
- The fit differs slightly by CPU platform: up to 2 points (B7, A10).
- The README names the real data that would settle the question: "the wearable, daily check-ins and dated ER visits and admissions, for a few hundred survivors on treatment over several months."

### B10. Reproduce

The same command as A10. The urgent head is trained in `analysis/train.py`. Its CIs come from `analysis/urgent_ci.py` → `analysis/out/urgent_ci.json`. `urgent_ci.py` asserts that its threshold matches the one stored by `train.py` in `gbm.pkl`.

---

## C. Rule-based checks (no model)

### C1. Diary-note safety scan (English, Spanish, Haitian Creole)

- **What fires** (`analysis/notes_scan.py`, `LEXICON`, `categories`): a fixed word list per red flag and language. The red flags are fever or chills, can't keep fluids down, called the care team, breathing or chest pain, bleeding, a fall, and distress. A hit sets `reviewToday` and adds "Read today's diary note and call today" as the first action. It does not change any score.
- Notes about an ER visit or hospital stay that already happened are their own category (`already_in_care`). They never count as a warning.
- **Written first**: the word list was written from the note templates of all patients, before looking at outcomes. 35 failure cases were written first, including false alarms such as "too hot to walk" and "hot flashes". All must pass, or the script stops (`self_test`).

| Held-out patients (182 ER/admissions) | ER caught 2–7 d early | ER within 7 d when flagged | Flag days / patient / month |
|---|---|---|---|
| Urgent tier alone (the baseline here) | 47% | 7.7% | 0.80 |
| **Urgent tier + note scan** | **57%** | 8.6% | 0.84 |
| Note scan alone | 18% | 27% (about 23x the usual) | 0.05 |

- **Gain from the notes**: +10 points of ER visits caught, 95% CI **+6 to +15** (paired patient bootstrap, `urgent_ci.py`). The CI excludes zero.
- Fever notes are followed by an ER visit or admission 49% of the time, and calls to the nurse 44%.
- **By language** (calendar → urgent → urgent + notes): English 36% → 51% → 60%, Spanish 32% → 40% → 54%, Haitian Creole 50% → 44% → 44%. **Creole speakers gain nothing from the notes yet.** In this data, Creole notes only mention tiredness, nausea, appetite or sleep. No real Creole red-flag notes exist here to test the Creole list on.
- **Why notes are not model inputs** (`analysis/exp/notes_features.py`): the notes were added to the rough-patch model under the same 3-day lag. The rule, fixed beforehand, was +0.005 validation AUC and no recall loss. Validation week AUC moved by -0.004 and recall by 0, so the notes stay out.

Source: `README.md`, `analysis/out/notes_scan.json`, `analysis/out/urgent_ci.json`, `analysis/out/exp_notes_features.json`.

### C2. Model-free red-flag escalation

- **Rules** (`analysis/escalation.py`, `passive_ideation`, `rules`): same-day "call today" rules, with no model and no score. The same input gives the same call on every platform. The rules are:
  - the note red-flag list from C1;
  - passive suicidal thinking in the note (English, Spanish, Creole patterns in `PASSIVE`). The coach calls today and follows the program's suicide-risk protocol;
  - a check-in rule.
- **Mood**: weekly sadness or worry at 4 of 4 means "call this week". It is counted but not validated, because an ER visit is the wrong outcome for it.
- **Check-in rule selection**: four candidate rules (C1–C4) and the selection rule were fixed before running. On validation patients, the rule with the highest share of flag days followed by an ER visit wins, among rules with at most 0.5 flag days per patient-month. The picked rule is **C1: daily feeling 1 of 5**. It was then scored once on test.
- **Written first**: 32 failure cases were set down before the rules. They include idioms that must not fire ("dying to see my grandkids", "me muero de ganas", "mwen mouri ri"), missing check-ins, and notes about an ER visit that already happened. All must pass, or the script stops.

| Held-out patients (182 ER/admissions), caseload 60 per coach | ER caught 2–7 d early | Calls per coach per week | Calls per ER visit or admission that follows |
|---|---|---|---|
| Escalation alone (model-free) | 32% | 4.4 | 8 |
| Urgent tier alone (the baseline here) | 47% | 11.9 | 13 |
| **Urgent tier + escalation** | **61%** | 15.5 | 12 |

- **Gain**: 61% vs 47%, 95% CI **+9 to +19 points** (paired patient bootstrap, `urgent_ci.boot`). The CI excludes zero. The cost is about 4 more calls per coach per week.
- **By language**: the escalation fires 0.31, 0.33 and 0.33 times per patient-month for English, Creole and Spanish speakers. With the urgent tier it catches 64%, 50% and 60% of ER visits. Creole has 18 events.
- **Limits** (`README.md`):
  - No passive-ideation phrase occurs in this synthetic data (`ideation_notes_in_data` = 0). That rule is tested only on the written cases, with no outcome.
  - Negations over-call: "I don't want to die" fires. This is accepted, because a call is cheap and a miss is not.
  - Coach text is English only.
  - Caseload 60 is a stated parameter. The sponsor brief gives no caseload.
- **Reproducibility**: the escalation-only numbers reproduce exactly on macOS and Linux. The rows combined with the urgent tier fall under the platform tolerance.

Source: `README.md`, `analysis/out/escalation.json`.

---

## Generative AI

None. The module makes no LLM, speech-to-text or other generative model call (`README.md`: "no LLM step needed"). Explanations and suggested actions are fixed templates filled with numbers (`analysis/export.py`).

## Future work

From `README.md` ("Asked for by the judges panel. Not built"):
- Spanish and Haitian Creole coach and patient text, at a 6th-grade level, marked machine-translated and reviewed by native speakers.
- A mitigation for the weaker groups (Haitian Creole speakers, sarcoma): per-group alert lines, a pooled fallback or care-team review, with a monitoring rule.
- A table that compares the cohort's make-up with Miami-Dade.
- Repeated patient-split seeds, **calibration on the temporal holdout**, and a drift monitor. Only one temporal holdout was run.

## Code map

| Step | File (function) |
|---|---|
| Load sponsor data | `analysis/train.py` (`load`) |
| Label v1 and clinical events | `analysis/train.py` (`label`) |
| Label v2: personal baselines, skip runs, optional proxy | `analysis/train.py` (`label_v2`, `_personal_base`, `_skip_streak`) |
| Patch, onset, 7-day target | `analysis/train.py` (`episodes`) |
| Wearable + calendar features | `analysis/train.py` (`features`, `cycle_len`) |
| Check-in features, 3-day lag | `analysis/train.py` (`checkin_features`, `CHECKIN_LAG`) |
| Patient split, fitting, thresholds on validation | `analysis/train.py` (`main`) |
| Logistic comparison | `analysis/train.py` (`fit_lr`, `lr_score`) |
| Week and episode metrics | `analysis/train.py` (`week_metrics`, `episode_metrics`) |
| Urgent head metrics | `analysis/train.py` (`urgent_metrics`) |
| Calibration deciles and Brier | `analysis/train.py` (`calibration`) |
| Subgroups with patient-bootstrap recall CI | `analysis/train.py` (`subgroups`) |
| Paired patient-bootstrap lift CIs | `analysis/train.py` (`bootstrap_lift`, `_patient_hits`) |
| Urgent and note-scan CIs, by language | `analysis/urgent_ci.py` (`per_patient`, `boot`) |
| Diary-note scan | `analysis/notes_scan.py` (`categories`, `self_test`, `er_window_hits`) |
| Model-free escalation | `analysis/escalation.py` (`passive_ideation`, `rules`, `self_test`, `evaluate`) |
| Real-data check | `analysis/real_check.py` (script body) |
| Temporal holdout | `analysis/exp/temporal_holdout.py` (`main`) |
| Notes as inputs | `analysis/exp/notes_features.py` (`note_features`, `main`) |
| Label cross-check (historical) | `analysis/exp/label_crosscheck.py` |
| ER pre-signal | `analysis/exp/er_presignal.py` |
| Check-in / surprise / worklist experiment | `analysis/exp/checkin_worklist.py` |
| Explanations, actions, headline, fairness, provenance, export | `analysis/export.py` (`drivers`, `describe`, `describe_checkins`, `actions`, `social_needs`, `escalation_today`, `headline_block`, `fairness_block`, `provenance`, `main`) |
| Serve the API | `src/index.ts` |
| One-command reproduce and number check | `scripts/reproduce.sh`, `scripts/check_numbers.py`, `analysis/expected.json` |
| Fresh clone on Cloudflare | `scripts/repro-cloudflare.sh`, `runner/` |
| E2E, contract and page check against the live Worker | `scripts/e2e.mjs`, `scripts/contract.mjs`, `scripts/page-check.mjs` |

Note for code readers: the module docstring at the top of `analysis/train.py` says self-reports are "never used as inputs". That predates the check-in features. The current code uses lagged check-in values as inputs (`checkin_features`). Events and diary text are still never inputs.
