"""Real-data check on the fatigue study (Rao et al. 2023): do the Radar's wearable signals move on real bad days,
and do they move in the days BEFORE a bad day?

Usage: .venv/bin/python -I analysis/real_check.py <path to Challenge3_Bad_Week_Radar>
Writes analysis/out/real_check.json (export.py folds it into the served metrics).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]).expanduser()
SIG = ["steps", "resting_heart_rate", "sleep_minutes", "sleep_efficiency_pct", "minutes_brisk_activity",
       "avg_heart_rate_asleep", "minutes_fitbit_worn"]

d = pd.read_csv(SRC / "fatigue_study_daily.csv", parse_dates=["date"]).sort_values(["person_id", "date"])
d = d[d.steps.notna() & d.bad_day.notna()].copy()
g = d.groupby("person_id")
for s in SIG:
    mu, sd = g[s].transform("median"), g[s].transform("std").replace(0, np.nan)
    d[f"{s}_z"] = (d[s] - mu) / sd
    # mean of the 2 days before (not including) the day being predicted
    d[f"{s}_prev2"] = d.groupby("person_id")[f"{s}_z"].transform(lambda v: v.shift(1).rolling(2, min_periods=1).mean())

same_day = {s: {"bad_days_z": round(float(d.loc[d.bad_day == 1, f"{s}_z"].mean()), 3),
                "other_days_z": round(float(d.loc[d.bad_day == 0, f"{s}_z"].mean()), 3)} for s in SIG}

# next-day forecast from the previous 2 days of wearable only, leave-people-out
X = d[[f"{s}_prev2" for s in SIG]].fillna(0)
y = d.bad_day.astype(int).values
pred = np.zeros(len(d))
for tr, te in GroupKFold(5).split(X, y, d.person_id):
    pred[te] = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
auc_wear = roc_auc_score(y, pred)
# yesterday's own rating as the honest comparison (what the person would say)
d["prev_bad"] = g.bad_day.shift(1)
m = d.prev_bad.notna()
auc_prev = roc_auc_score(y[m.values], d.loc[m, "prev_bad"])

out = {
    "dataset": "fatigue_study_daily.csv (Rao et al. 2023), people with a Fitbit",
    "people": int(d.person_id.nunique()), "days": int(len(d)), "bad_day_share": round(float(y.mean()), 3),
    "same_day_signal_z": same_day,
    "next_day_auc_wearable_only_prev2days": round(float(auc_wear), 3),
    "next_day_auc_yesterdays_self_rating": round(float(auc_prev), 3),
    "note": "z = standard deviations from the person's own median. Leave-people-out 5-fold CV.",
}
(ROOT / "analysis" / "out" / "real_check.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
