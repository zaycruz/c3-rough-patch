# Reproduce C3 Bad Week Radar

One command takes you from the sponsor download to every number in [README.md](README.md). It then checks each number against the README.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.12 or later. It installs Python 3.14 (`.python-version`) and the exact packages in `uv.lock` (numpy, pandas, pyarrow, scikit-learn, scipy).
- git, with **full history**. Do not use a shallow clone, because the historical cross-check reruns `train.py` from commit `d72545d`.
- Node 22 and `npm ci` are only needed for the Worker, the E2E check and the contract (the versions are locked in `package-lock.json`).
- CPU only. About 6 GB of RAM. No GPU.

From the monorepo: `git clone --recurse-submodules https://github.com/zaycruz/survivorship-360 && cd survivorship-360/modules/c3-rough-patch`.
Or clone this repo alone: `git clone https://github.com/zaycruz/c3-rough-patch && cd c3-rough-patch`.

## 1. Data

Put the sponsor folder at `data/Challenge3_Bad_Week_Radar/`. [data/README.md](data/README.md) lists the expected files, their sha256 hashes and where the real data comes from. The script checks the hashes before it does anything else.

## 2. The one command

```bash
scripts/reproduce.sh data/Challenge3_Bad_Week_Radar          # full (see the time per step in the latest runs/reproduce-*.md)
scripts/reproduce.sh data/Challenge3_Bad_Week_Radar quick    # served pipeline only, skips the historical cross-check
```

It runs these steps in order. Each one has a fixed seed (`SEED` in `analysis/train.py`).

| Step | Script | Writes |
|---|---|---|
| Label, features, models, held-out evaluation, calibration, subgroups, bootstrap CIs, urgent tier | `analysis/train.py` | `analysis/out/metrics.json` (+ `gbm.pkl`, parquet files, git-ignored) |
| Real-data check (fatigue study) | `analysis/real_check.py` | `analysis/out/real_check.json` |
| Diary-note red-flag scan (English, Spanish, Haitian Creole): 35 written-first cases, then held-out evaluation | `analysis/notes_scan.py` | `analysis/out/notes_scan.json` |
| Urgent tier vs the calendar-only ER model, and the note-scan gain: patient-bootstrap CIs, by language | `analysis/urgent_ci.py` | `analysis/out/urgent_ci.json` |
| Notes as rough-patch model inputs (decision rule fixed beforehand) | `analysis/exp/notes_features.py` | `analysis/out/exp_notes_features.json` |
| Caseload, explanations, actions, headline and fairness blocks served by the API; the precomputed roster | `analysis/export.py` | `src/data/survivors.json`, `src/data/metrics.json`, `public/api/c3/survivors` |
| Wearable signals before an ER visit | `analysis/exp/er_presignal.py` | `analysis/out/er_presignal.json` |
| Check-in / surprise / worklist experiment (picked on val, scored once on test) | `analysis/exp/checkin_worklist.py` | `analysis/out/exp_checkin_worklist_{val,test}.json` |
| *full only:* label v2 before check-ins, the proxy-label variant (`C3_PROXY=1`) and the matched-budget label cross-check | `train.py` from commit `d72545d`, `analysis/exp/label_crosscheck.py` | `analysis/out/historical/*.json` |
| Compare every README number with this run | `scripts/check_numbers.py` (expectations in `analysis/expected.json`) | the table in the log |

The log goes to `runs/reproduce-<UTC stamp>.md`. It records where the run happened, the commit, the uv/Python/package versions, the data hashes, the time per step, the README-number table (match / MISMATCH / MISSING) and a `git diff --stat` of the served files. The script exits non-zero if any number does not match (within the platform tolerance below).

### Platform tolerance (macOS vs Linux)

The README numbers were made on macOS arm64. On Linux x86_64 (the Cloudflare fresh clone, `runs/reproduce-2026-10-17T17-18-10Z.md`) every rough-patch number, fairness number and real-data number matches exactly. Two parts do not: the urgent ER head (and everything built on it: its CI, the note-scan gain, the by-language ER rows) and the historical proxy-label run. Same code, seed, data and package versions; the gradient-boosting fit differs slightly by CPU platform.

Those 18 rows are listed under `platform_tolerance` in `analysis/expected.json`. `check_numbers.py` passes them as `match (platform tolerance, ...)` when:
- **percentages and CI points:** the printed value is within 2 points, or, for a language group, within 2 ER events of that group (Creole has 18 test ER events, so 1 event is 6 points);
- **rates and AUCs:** within the stated amount (0.03 flags/patient/month, 0.005 AUC, 0.05 patches/patient).

Every other row must match exactly. What changes on Linux: urgent ER caught 49% (README 47%), CI +4 to +21 (README +2 to +19); urgent + notes 58% (57%); Creole urgent 50% (44%), so on Linux the urgent tier does not lose ground for Creole speakers, and the notes still add nothing for them.

## 3. The proof: fresh clone on Cloudflare

`scripts/repro-cloudflare.sh <DATA_DIR> <sha>` runs the same command in a Cloudflare Sandbox container, not on a laptop:
1. It deploys `runner/` as a throwaway Worker with a one-off secret token.
2. It uploads the three sponsor files over HTTPS behind that token.
3. The container clones this repo at `<sha>` into an empty directory and runs `scripts/reproduce.sh`.
4. The script fetches the log into `runs/`, then destroys the container (data included) and deletes the Worker.

The committed proof is the newest `runs/reproduce-*.md` whose "Where" line says Cloudflare.

## 4. Model search and research

- `analysis/research_log.md`: every experiment, with what was selected on validation and what was scored once on test.
- Branch [`research/model-v2`](https://github.com/zaycruz/c3-rough-patch/tree/research/model-v2): the model-family bake-off (`analysis/families*.py`, `analysis/research.py`; HGB vs LightGBM, XGBoost, random forest, spline logistic, a CNN and ensembles). HGB won on validation, and it is the model served here. That branch needs extra packages (lightgbm, xgboost, torch, pycaret) and is not part of `reproduce.sh`.

## 5. E2E against the live Worker

```bash
npm ci
npm run e2e        # NODE_OPTIONS=--network-family-autoselection-attempt-timeout=3000 if your network is slow to connect
npm run contract   # rebuilds CONTRACT.md from that run
```

`npm run e2e` checks every endpoint and every survivor panel on https://c3-rough-patch.zay-259.workers.dev. It saves `runs/e2e-<time>.json` and `runs/e2e-latest.json`. To serve your own rebuilt `src/data`, run `npx tsc --noEmit && npx wrangler deploy`, then `node scripts/e2e.mjs <your workers.dev URL>`.

## README number → where it comes from

`scripts/check_numbers.py` checks every row below. Rows marked `train.py @ d72545d` reproduce numbers measured on an earlier version of the pipeline (label v2 before the check-ins became inputs). The full run reruns that version from git history.

**The ER pre-signal line was reworded during this work.** The README used to say "about 3 bpm and 850 steps", and that figure had no committed source: it came from an early exploratory command. It now cites `analysis/exp/er_presignal.py`, which uses a stated method (first ER visits, against the person's median on days -35 to -15). The model and every other number are unchanged.


| README number | File | Key | Expected (as README rounds it) | Source |
|---|---|---|---|---|
| Test patients | `analysis/out/metrics.json` | `counts.test_patients` | 750 | current pipeline |
| Test patient-weeks | `analysis/out/metrics.json` | `methods.model.weeks.weeks` | 14501 | current pipeline |
| Daily check-ins missing | `analysis/out/metrics.json` | `counts.label_missing_feeling_share` | 55% | current pipeline |
| Rough rate after 0 skips | `analysis/out/metrics.json` | `label_v2.rough_rate_after_skips.0` | 4.9% | current pipeline |
| Rough rate after 2 skips | `analysis/out/metrics.json` | `label_v2.rough_rate_after_skips.2` | 6.4% | current pipeline |
| Rough rate after 3 skips | `analysis/out/metrics.json` | `label_v2.rough_rate_after_skips.3` | 6.9% | current pipeline |
| Rough rate after 5+ skips | `analysis/out/metrics.json` | `label_v2.rough_rate_after_skips.5` | 8.6% | current pipeline |
| Patches per patient, most engaged | `analysis/out/metrics.json` | `label_v2.onsets_per_patient_by_checkin_engagement.most engaged` | 1.0 | current pipeline |
| Patches per patient, q2 | `analysis/out/metrics.json` | `label_v2.onsets_per_patient_by_checkin_engagement.q2` | 1.01 | current pipeline |
| Patches per patient, q3 | `analysis/out/metrics.json` | `label_v2.onsets_per_patient_by_checkin_engagement.q3` | 1.05 | current pipeline |
| Patches per patient, least engaged | `analysis/out/metrics.json` | `label_v2.onsets_per_patient_by_checkin_engagement.least engaged` | 0.96 | current pipeline |
| Steps drop: week AUC | `analysis/out/metrics.json` | `methods.steps_rule.weeks.auc` | 0.567 | current pipeline |
| Steps drop: week precision | `analysis/out/metrics.json` | `methods.steps_rule.weeks.precision` | 10% | current pipeline |
| Steps drop: week recall | `analysis/out/metrics.json` | `methods.steps_rule.weeks.recall` | 10% | current pipeline |
| Steps drop: patches caught | `analysis/out/metrics.json` | `methods.steps_rule.episodes.episode_recall` | 25% | current pipeline |
| Steps drop: median lead | `analysis/out/metrics.json` | `methods.steps_rule.episodes.median_lead_days` | 5 | current pipeline |
| Steps drop: alert precision | `analysis/out/metrics.json` | `methods.steps_rule.episodes.alert_precision` | 8% | current pipeline |
| Steps drop: alerts/patient/month | `analysis/out/metrics.json` | `methods.steps_rule.episodes.alerts_per_patient_month` | 0.66 | current pipeline |
| Calendar: week AUC | `analysis/out/metrics.json` | `methods.schedule.weeks.auc` | 0.808 | current pipeline |
| Calendar: week precision | `analysis/out/metrics.json` | `methods.schedule.weeks.precision` | 20% | current pipeline |
| Calendar: week recall | `analysis/out/metrics.json` | `methods.schedule.weeks.recall` | 26% | current pipeline |
| Calendar: patches caught | `analysis/out/metrics.json` | `methods.schedule.episodes.episode_recall` | 36% | current pipeline |
| Calendar: median lead | `analysis/out/metrics.json` | `methods.schedule.episodes.median_lead_days` | 7 | current pipeline |
| Calendar: alert precision | `analysis/out/metrics.json` | `methods.schedule.episodes.alert_precision` | 11% | current pipeline |
| Calendar: alerts/patient/month | `analysis/out/metrics.json` | `methods.schedule.episodes.alerts_per_patient_month` | 0.36 | current pipeline |
| Logistic: week AUC | `analysis/out/metrics.json` | `methods.logistic.weeks.auc` | 0.768 | current pipeline |
| Logistic: week precision | `analysis/out/metrics.json` | `methods.logistic.weeks.precision` | 16% | current pipeline |
| Logistic: week recall | `analysis/out/metrics.json` | `methods.logistic.weeks.recall` | 14% | current pipeline |
| Logistic: patches caught | `analysis/out/metrics.json` | `methods.logistic.episodes.episode_recall` | 25% | current pipeline |
| Logistic: median lead | `analysis/out/metrics.json` | `methods.logistic.episodes.median_lead_days` | 6 | current pipeline |
| Logistic: alert precision | `analysis/out/metrics.json` | `methods.logistic.episodes.alert_precision` | 13% | current pipeline |
| Logistic: alerts/patient/month | `analysis/out/metrics.json` | `methods.logistic.episodes.alerts_per_patient_month` | 0.33 | current pipeline |
| No check-ins: week AUC | `analysis/out/metrics.json` | `ablation_without_checkins.weeks.auc` | 0.819 | current pipeline |
| No check-ins: week precision | `analysis/out/metrics.json` | `ablation_without_checkins.weeks.precision` | 22% | current pipeline |
| No check-ins: week recall | `analysis/out/metrics.json` | `ablation_without_checkins.weeks.recall` | 24% | current pipeline |
| No check-ins: patches caught | `analysis/out/metrics.json` | `ablation_without_checkins.episodes.episode_recall` | 41% | current pipeline |
| No check-ins: median lead | `analysis/out/metrics.json` | `ablation_without_checkins.episodes.median_lead_days` | 5 | current pipeline |
| No check-ins: alert precision | `analysis/out/metrics.json` | `ablation_without_checkins.episodes.alert_precision` | 17% | current pipeline |
| No check-ins: alerts/patient/month | `analysis/out/metrics.json` | `ablation_without_checkins.episodes.alerts_per_patient_month` | 0.45 | current pipeline |
| Radar: week AUC | `analysis/out/metrics.json` | `methods.model.weeks.auc` | 0.827 | current pipeline |
| Radar: week precision | `analysis/out/metrics.json` | `methods.model.weeks.precision` | 23% | current pipeline |
| Radar: week recall | `analysis/out/metrics.json` | `methods.model.weeks.recall` | 28% | current pipeline |
| Radar: patches caught | `analysis/out/metrics.json` | `methods.model.episodes.episode_recall` | 48% | current pipeline |
| Radar: median lead | `analysis/out/metrics.json` | `methods.model.episodes.median_lead_days` | 6 | current pipeline |
| Radar: alert precision | `analysis/out/metrics.json` | `methods.model.episodes.alert_precision` | 18% | current pipeline |
| Radar: alerts/patient/month | `analysis/out/metrics.json` | `methods.model.episodes.alerts_per_patient_month` | 0.48 | current pipeline |
| Lift vs calendar, patches, CI low | `analysis/out/metrics.json` | `lift_vs_schedule_ci95.episode_recall_diff.0` | +8 | current pipeline |
| Lift vs calendar, patches, CI high | `analysis/out/metrics.json` | `lift_vs_schedule_ci95.episode_recall_diff.1` | +15 | current pipeline |
| Check-ins lift, patches, CI low | `analysis/out/metrics.json` | `ablation_without_checkins.lift_of_checkins_ci95.episode_recall_diff.0` | +3 | current pipeline |
| Check-ins lift, patches, CI high | `analysis/out/metrics.json` | `ablation_without_checkins.lift_of_checkins_ci95.episode_recall_diff.1` | +9 | current pipeline |
| Calibration: top decile predicted | `analysis/out/metrics.json` | `calibration.model.deciles.-1.predicted` | 19% | current pipeline |
| Calibration: top decile observed | `analysis/out/metrics.json` | `calibration.model.deciles.-1.observed` | 19% | current pipeline |
| Brier, model | `analysis/out/metrics.json` | `calibration.model.brier` | 0.0407 | current pipeline |
| Brier, base rate | `analysis/out/metrics.json` | `calibration.model.brier_if_base_rate` | 0.0445 | current pipeline |
| Urgent: ER/admissions in test | `analysis/out/metrics.json` | `urgent.methods.urgent.er_events` | 182 | current pipeline |
| Urgent head: ER caught | `analysis/out/metrics.json` | `urgent.methods.urgent.er_recall_2to7d` | 47% | current pipeline |
| Urgent head: median lead | `analysis/out/metrics.json` | `urgent.methods.urgent.median_lead_days` | 4 | current pipeline |
| Urgent head: flag precision | `analysis/out/metrics.json` | `urgent.methods.urgent.flag_precision` | 7.4% | current pipeline |
| Urgent head: flags/patient/month | `analysis/out/metrics.json` | `urgent.methods.urgent.flags_per_patient_month` | 0.38 | current pipeline |
| Urgent head: AUC | `analysis/out/metrics.json` | `urgent.methods.urgent.auc` | 0.859 | current pipeline |
| Urgent head: avg precision | `analysis/out/metrics.json` | `urgent.methods.urgent.average_precision` | 0.064 | current pipeline |
| Urgent base rate | `analysis/out/metrics.json` | `urgent.methods.urgent.base_rate` | 1.2% | current pipeline |
| Calendar-only ER model: ER caught | `analysis/out/metrics.json` | `urgent.methods.schedule.er_recall_2to7d` | 36% | current pipeline |
| Calendar-only ER model: median lead | `analysis/out/metrics.json` | `urgent.methods.schedule.median_lead_days` | 5 | current pipeline |
| Calendar-only ER model: flag precision | `analysis/out/metrics.json` | `urgent.methods.schedule.flag_precision` | 6.9% | current pipeline |
| Calendar-only ER model: flags/patient/month | `analysis/out/metrics.json` | `urgent.methods.schedule.flags_per_patient_month` | 0.23 | current pipeline |
| Calendar-only ER model: AUC | `analysis/out/metrics.json` | `urgent.methods.schedule.auc` | 0.845 | current pipeline |
| Calendar-only ER model: avg precision | `analysis/out/metrics.json` | `urgent.methods.schedule.average_precision` | 0.0486 | current pipeline |
| Radar at 3%: ER caught | `analysis/out/metrics.json` | `urgent.methods.radar.er_recall_2to7d` | 29% | current pipeline |
| Radar at 3%: median lead | `analysis/out/metrics.json` | `urgent.methods.radar.median_lead_days` | 6 | current pipeline |
| Radar at 3%: flag precision | `analysis/out/metrics.json` | `urgent.methods.radar.flag_precision` | 6.1% | current pipeline |
| Radar at 3%: flags/patient/month | `analysis/out/metrics.json` | `urgent.methods.radar.flags_per_patient_month` | 0.27 | current pipeline |
| Radar at 3%: AUC | `analysis/out/metrics.json` | `urgent.methods.radar.auc` | 0.788 | current pipeline |
| Radar at 3%: avg precision | `analysis/out/metrics.json` | `urgent.methods.radar.average_precision` | 0.0362 | current pipeline |
| Urgent vs calendar-only ER model, CI low | `analysis/out/urgent_ci.json` | `urgent_minus_calendar_ci95.0` | +2 | current pipeline |
| Urgent vs calendar-only ER model, CI high | `analysis/out/urgent_ci.json` | `urgent_minus_calendar_ci95.1` | +19 | current pipeline |
| Urgent flag: times the usual risk | `src/data/metrics.json` | `headline.urgent.timesUsualRisk` | 6 | current pipeline |
| Note scan: written-first cases | `analysis/out/notes_scan.json` | `self_test.cases` | 35 | current pipeline |
| Note scan + urgent: ER caught | `analysis/out/urgent_ci.json` | `er_caught_2to7d.urgent_or_note` | 57% | current pipeline |
| Note scan gain, CI low | `analysis/out/urgent_ci.json` | `note_scan_gain_ci95.0` | +6 | current pipeline |
| Note scan gain, CI high | `analysis/out/urgent_ci.json` | `note_scan_gain_ci95.1` | +15 | current pipeline |
| Note scan alone: ER caught | `analysis/out/notes_scan.json` | `evaluation.test.flags.note_scan.er_caught_2to7d` | 18% | current pipeline |
| Note scan alone: ER within 7 d when flagged | `analysis/out/notes_scan.json` | `evaluation.test.flags.note_scan.er_within_7d_when_flagged` | 27% | current pipeline |
| Note scan alone: times the usual | `analysis/out/notes_scan.json` | `evaluation.test.flags.note_scan.times_base_rate` | 23 | current pipeline |
| Note scan alone: flags/patient/month | `analysis/out/notes_scan.json` | `evaluation.test.flags.note_scan.flag_days_per_patient_month` | 0.05 | current pipeline |
| Urgent tier alone: ER within 7 d when flagged (days) | `analysis/out/notes_scan.json` | `evaluation.test.flags.urgent_tier.er_within_7d_when_flagged` | 7.7% | current pipeline |
| Urgent + notes: ER within 7 d when flagged (days) | `analysis/out/notes_scan.json` | `evaluation.test.flags.urgent_or_note.er_within_7d_when_flagged` | 8.6% | current pipeline |
| Urgent tier alone: flag days/patient/month | `analysis/out/notes_scan.json` | `evaluation.test.flags.urgent_tier.flag_days_per_patient_month` | 0.80 | current pipeline |
| Urgent + notes: flag days/patient/month | `analysis/out/notes_scan.json` | `evaluation.test.flags.urgent_or_note.flag_days_per_patient_month` | 0.84 | current pipeline |
| Fever notes: ER within 7 d | `analysis/out/notes_scan.json` | `evaluation.test.by_category.fever_infection.er_within_7d` | 49% | current pipeline |
| Nurse-call notes: ER within 7 d | `analysis/out/notes_scan.json` | `evaluation.test.by_category.called_care_team.er_within_7d` | 44% | current pipeline |
| By language: English, calendar | `analysis/out/urgent_ci.json` | `by_language.English.calendar` | 36% | current pipeline |
| By language: English, urgent | `analysis/out/urgent_ci.json` | `by_language.English.urgent` | 51% | current pipeline |
| By language: English, urgent + notes | `analysis/out/urgent_ci.json` | `by_language.English.urgent_or_note` | 60% | current pipeline |
| By language: Spanish, calendar | `analysis/out/urgent_ci.json` | `by_language.Spanish.calendar` | 32% | current pipeline |
| By language: Spanish, urgent | `analysis/out/urgent_ci.json` | `by_language.Spanish.urgent` | 40% | current pipeline |
| By language: Spanish, urgent + notes | `analysis/out/urgent_ci.json` | `by_language.Spanish.urgent_or_note` | 54% | current pipeline |
| By language: Creole, calendar | `analysis/out/urgent_ci.json` | `by_language.Haitian Creole.calendar` | 50% | current pipeline |
| By language: Creole, urgent | `analysis/out/urgent_ci.json` | `by_language.Haitian Creole.urgent` | 44% | current pipeline |
| By language: Creole, urgent + notes | `analysis/out/urgent_ci.json` | `by_language.Haitian Creole.urgent_or_note` | 44% | current pipeline |
| By language: Creole ER events | `analysis/out/urgent_ci.json` | `by_language.Haitian Creole.er_events` | 18 | current pipeline |
| Notes as inputs: val week AUC change | `analysis/out/exp_notes_features.json` | `val_change.week_auc` | -0.004 | current pipeline |
| Notes as inputs: val recall change | `analysis/out/exp_notes_features.json` | `val_change.episode_recall` | 0 | current pipeline |
| Fairness: overall week recall | `src/data/metrics.json` | `fairness.overallRecall` | 28% | current pipeline |
| Fairness: sarcoma recall | `src/data/metrics.json` | `fairness.@cancer_type.sarcoma.recall` | 13% | current pipeline |
| Fairness: sarcoma CI high | `src/data/metrics.json` | `fairness.@cancer_type.sarcoma.recallCi95.1` | 26% | current pipeline |
| Fairness: Haitian Creole recall | `src/data/metrics.json` | `fairness.@preferred_language.Haitian Creole.recall` | 22% | current pipeline |
| Fairness: Haitian Creole CI low | `src/data/metrics.json` | `fairness.@preferred_language.Haitian Creole.recallCi95.0` | 10% | current pipeline |
| Fairness: Haitian Creole CI high | `src/data/metrics.json` | `fairness.@preferred_language.Haitian Creole.recallCi95.1` | 36% | current pipeline |
| Fairness: breast recall | `src/data/metrics.json` | `fairness.@cancer_type.breast.recall` | 21% | current pipeline |
| Fairness: breast CI low | `src/data/metrics.json` | `fairness.@cancer_type.breast.recallCi95.0` | 14% | current pipeline |
| Fairness: breast CI high | `src/data/metrics.json` | `fairness.@cancer_type.breast.recallCi95.1` | 28% | current pipeline |
| Real data: people with a Fitbit | `analysis/out/real_check.json` | `people` | 204 | current pipeline |
| Real data: steps z on bad days | `analysis/out/real_check.json` | `same_day_signal_z.steps.bad_days_z` | -0.235 | current pipeline |
| Real data: steps z on other days | `analysis/out/real_check.json` | `same_day_signal_z.steps.other_days_z` | 0.073 | current pipeline |
| Real data: next-day AUC, wearable | `analysis/out/real_check.json` | `next_day_auc_wearable_only_prev2days` | 0.482 | current pipeline |
| Real data: next-day AUC, yesterday's rating | `analysis/out/real_check.json` | `next_day_auc_yesterdays_self_rating` | 0.64 | current pipeline |
| Worklist: precision of top-5 list (test) | `analysis/out/historical/exp_checkin_worklist_test.json` | `worklist.top5_of_60_per_day.check-ins + wearable + calendar.precision_at_k` | 8% | train.py @ d72545d |
| Worklist: base rate (test) | `analysis/out/historical/exp_checkin_worklist_test.json` | `base_rate_scored_days` | 4.7% | train.py @ d72545d |
| Worklist: patches reached by list (test) | `analysis/out/historical/exp_checkin_worklist_test.json` | `worklist.top5_of_60_per_day.check-ins + wearable + calendar.onsets_reached_2to7d` | 90% | train.py @ d72545d |
| Worklist: patches reached, calendar (test) | `analysis/out/historical/exp_checkin_worklist_test.json` | `worklist.top5_of_60_per_day.calendar only.onsets_reached_2to7d` | 88% | train.py @ d72545d |
| ER pre-signal: resting HR, last week | `analysis/out/er_presignal.json` | `days_1_to_7_mean.rhr_bpm` | 1.9 | current pipeline |
| ER pre-signal: steps, last week | `analysis/out/er_presignal.json` | `days_1_to_7_mean.steps` | -670 | current pipeline |
| ER pre-signal: resting HR, day before | `analysis/out/er_presignal.json` | `by_days_before.1.resting_hr_vs_baseline_bpm` | 4.2 | current pipeline |
| ER pre-signal: steps, day before | `analysis/out/er_presignal.json` | `by_days_before.1.steps_vs_baseline` | -2300 | current pipeline |
| Demo: roster alert | `src/data/survivors.json` | `#status.alert` | 5 | current pipeline |
| Demo: roster watch | `src/data/survivors.json` | `#status.watch` | 4 | current pipeline |
| Demo: roster ok | `src/data/survivors.json` | `#status.ok` | 51 | current pipeline |
| Demo: urgent | `src/data/survivors.json` | `#urgent` | 2 | current pipeline |
| Demo: P02836 risk | `src/data/survivors.json` | `@c3-P02836.risk` | 34% | current pipeline |
| Demo: P02465 risk | `src/data/survivors.json` | `@c3-P02465.risk` | 51% | current pipeline |
| Proxy label: Radar week AUC | `analysis/out/historical/metrics_v2_proxy.json` | `methods.model.weeks.auc` | 0.843 | train.py @ d72545d |
| Proxy label: calendar week AUC | `analysis/out/historical/metrics_v2_proxy.json` | `methods.schedule.weeks.auc` | 0.844 | train.py @ d72545d |
| Proxy label: patches/patient, least engaged | `analysis/out/historical/metrics_v2_proxy.json` | `label_v2.onsets_per_patient_by_checkin_engagement.least engaged` | 1.95 | train.py @ d72545d |
| Proxy label: patches/patient, most engaged | `analysis/out/historical/metrics_v2_proxy.json` | `label_v2.onsets_per_patient_by_checkin_engagement.most engaged` | 1.4 | train.py @ d72545d |
| Cross-check: v2 model on v2 onsets, week AUC | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model.week_auc` | 0.819 | train.py @ d72545d |
| Cross-check: v2 model on v2 onsets, recall | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model.episode_recall` | 66% | train.py @ d72545d |
| Cross-check: v1 model on v2 onsets, week AUC | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model_v1label.week_auc` | 0.815 | train.py @ d72545d |
| Cross-check: v1 model on v2 onsets, recall | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model_v1label.episode_recall` | 69% | train.py @ d72545d |
| Cross-check: v1 model alerts/patient/month | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model_v1label.alerts_per_patient_month` | 0.84 | train.py @ d72545d |
| Cross-check: v2 model alerts/patient/month | `analysis/out/historical/label_crosscheck.json` | `v2_onsets.score_model.alerts_per_patient_month` | 0.78 | train.py @ d72545d |
| Cross-check: v1 onsets, v1-trained week AUC | `analysis/out/historical/metrics_v2_noproxy.json` | `label_v2.cross_check.v1_onsets.week_auc.trained_on_v1` | 0.804 | train.py @ d72545d |
| Cross-check: v1 onsets, v2-trained week AUC | `analysis/out/historical/metrics_v2_noproxy.json` | `label_v2.cross_check.v1_onsets.week_auc.trained_on_v2` | 0.799 | train.py @ d72545d |
