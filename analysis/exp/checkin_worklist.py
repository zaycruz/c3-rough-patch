"""Experiment: does adding the person's own check-ins (feeling, symptoms, skips) make alerts useful?
And is alerting on the *surprise* (risk above the calendar) or a daily top-5 worklist better than a fixed threshold?

Leakage guard: the scoring mask drops days inside a patch, and a patch day is "rough + another rough within 3 days".
So on a scored day, a rough check-in at t..t-2 reveals that t+1..t+3 are not rough. Self-report VALUES therefore
use check-ins up to t-3 only. Whether a check-in happened (skips, days since) is used up to t: a skip is never rough.
Usage: .venv/bin/python -I analysis/exp/checkin_worklist.py   (needs analysis/out/scored.parquet, features.parquet)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))
import train as T  # noqa: E402

LAG = 3
d = pd.read_parquet(ROOT / "analysis/out/scored.parquet")
F = pd.read_parquet(ROOT / "analysis/out/features.parquet")
g = d.groupby("patient_id")
feel = d.daily_feeling_1_to_5
base = T._personal_base(d, "daily_feeling_1_to_5", 5)
rel = feel - base
sym = d[T.SYMPTOMS].max(axis=1)
symb = pd.concat([T._personal_base(d, c, 2, window=8) for c in T.SYMPTOMS], axis=1).max(axis=1)
C = pd.DataFrame(index=d.index)
lag = lambda s: s.groupby(d.patient_id).shift(LAG)
C["feel_last"] = lag(feel).groupby(d.patient_id).ffill()
C["feel_rel_last"] = lag(rel).groupby(d.patient_id).ffill()
C["feel_rel_mean7"] = lag(rel).groupby(d.patient_id).transform(lambda s: s.rolling(7, min_periods=1).mean())
C["rough_self_14"] = lag(d.rough_self.astype(float)).groupby(d.patient_id).transform(lambda s: s.rolling(14, min_periods=1).sum())
C["sym_max_last"] = lag(sym).groupby(d.patient_id).ffill()
C["sym_rel_last"] = lag(sym - symb).groupby(d.patient_id).ffill()
miss = feel.isna()
C["skip_run"] = np.where(miss, d.skips_before + 1, 0)
C["checkin_rate14"] = (~miss).astype(float).groupby(d.patient_id).transform(lambda s: s.rolling(14, min_periods=1).mean())
roll = lambda s, n: s.astype(float).groupby(d.patient_id).transform(lambda v: v.rolling(n, min_periods=1).sum())
C["calls_missed_28"] = roll(d.coaching_call.isin(["missed", "rescheduled"]), 28)
C["calls_done_14"] = roll(d.coaching_call == "completed", 14)

use = (d.in_episode == 0) & (d.day_in_program >= 14)
tr, va, te = [(use & (d.split == k)).values for k in ("train", "val", "test")]
y = d.target.values
X_all = pd.concat([F, C], axis=1)
X_chk = pd.concat([F[T.SCHEDULE], C], axis=1)
hgb = lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=T.SEED)
d["score_checkin_all"] = hgb().fit(X_all[tr], y[tr]).predict_proba(X_all)[:, 1]
d["score_checkin_only"] = hgb().fit(X_chk[tr], y[tr]).predict_proba(X_chk)[:, 1]
d["surprise_model"] = d.score_model - d.score_schedule
d["surprise_checkin_all"] = d.score_checkin_all - d.score_schedule

# selection happens on validation patients (thresholds and metrics both on val, same budget for every method);
# EVAL=test reruns the same table on test once the choice is made
import os
EVAL = os.environ.get("EVAL", "val")
test, val = d[d.split == EVAL], d[va]
NAMES = {"score_schedule": "calendar only", "score_model": "wearable + calendar (live)",
         "score_checkin_only": "check-ins + calendar", "score_checkin_all": "check-ins + wearable + calendar",
         "surprise_model": "surprise: wearable vs calendar", "surprise_checkin_all": "surprise: check-ins+wearable vs calendar"}
out = {"eval_split": EVAL, "threshold": {}, "worklist": {}}
for budget in (0.12, 0.05):
    rows = {}
    for k, nm in NAMES.items():
        thr = float(np.quantile(val[k], 1 - budget))
        e, w = T.episode_metrics(test, k, thr), T.week_metrics(test, k, thr)
        rows[nm] = {"week_auc": w["auc"], "patch_recall": e["episode_recall"], "er_recall": e["er_recall"],
                    "alert_precision": e["alert_precision"], "week_precision": w["precision"],
                    "alerts_per_patient_month": e["alerts_per_patient_month"]}
    out["threshold"][f"budget_{int(budget*100)}pct"] = rows

# worklist: test patients in caseloads of 60; each evening the coach gets the top K not already in a patch
rng = np.random.default_rng(T.SEED)
tp = test.patient_id.unique().copy(); rng.shuffle(tp)
cl = {p: i // 60 for i, p in enumerate(tp)}
q = test[(test.day_in_program >= 14)].assign(caseload=lambda x: x.patient_id.map(cl))
q = q[q.in_episode == 0]
onsets = test[(test.onset == 1) & (test.day_in_program >= 14)][["patient_id", "date"]]
for K in (3, 5):
    rows = {}
    for k, nm in NAMES.items():
        top = q.sort_values(k, ascending=False).groupby(["caseload", "date"]).head(K)
        prec = float(top.target.mean())
        hit = top[["patient_id", "date"]]
        m = onsets.merge(hit, on="patient_id", suffixes=("", "_h"))
        lead = (m.date - m.date_h).dt.days
        reached = m[(lead >= T.MIN_LEAD) & (lead <= T.HORIZON)].drop_duplicates(["patient_id", "date"])
        rows[nm] = {"precision_at_k": round(prec, 3), "onsets_reached_2to7d": round(len(reached) / len(onsets), 3)}
    out["worklist"][f"top{K}_of_60_per_day"] = rows
out["base_rate_scored_days"] = round(float(q.target.mean()), 4)
out["onsets_test"] = int(len(onsets))
(ROOT / f"analysis/out/exp_checkin_worklist_{EVAL}.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=1))
