"""Experiment: temporal holdout. Train on earlier dates, test on later dates (and on patients never seen).

Usage: python -I analysis/exp/temporal_holdout.py      (after analysis/train.py)
Writes: analysis/out/exp_temporal_holdout.json

Design, fixed before running:
- Train: train- and validation-split patients, dates before TRAIN_END - 7 days (the label looks 7 days ahead, so no
  training label can see past TRAIN_END).
- Alert line: validation-split patients, dates TRAIN_END .. TEST_START - 7 days, 5% of quiet days (as in train.py).
- Test: test-split patients, dates from TEST_START on: later in time AND people the model never saw.
- Same learner, seed, features, label and 5% alert budget as train.py; the calendar-only rough-patch model is refit the
  same way and is the baseline. Report whatever it shows.
Known limits: features are per-person rolling values (past only), so they are unaffected; the stored label's personal
baselines are also past-only. The rough-day nowcast inside label v2 was fit on train-split patients over all dates.
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

OUT = ROOT / "analysis" / "out"
TRAIN_END, TEST_START = pd.Timestamp("2025-07-01"), pd.Timestamp("2025-10-01")
GAP = pd.Timedelta(days=7)


def main():
    d = pd.read_parquet(OUT / "scored.parquet")
    F = pd.read_parquet(OUT / "features.parquet")
    assert len(F) == len(d) and (F.index == d.index).all()
    feats = list(F.columns)
    use = (d.in_episode == 0) & (d.day_in_program >= 14)
    tr = (use & d.split.isin(["train", "val"]) & (d.date < TRAIN_END - GAP)).values
    va = (use & (d.split == "val") & (d.date >= TRAIN_END) & (d.date < TEST_START - GAP)).values
    y = d.target.values
    fit = lambda cols: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=T.SEED).fit(F.loc[tr, cols], y[tr])
    d["score_model"] = fit(feats).predict_proba(F[feats])[:, 1]
    d["score_schedule"] = fit(T.SCHEDULE).predict_proba(F[T.SCHEDULE])[:, 1]
    thr = {k: {"alert": float(np.quantile(d.loc[va, f"score_{k}"], 1 - 0.05))} for k in ("model", "schedule")}
    test = d[(d.split == "test") & (d.date >= TEST_START)]
    res = {"design": {"train": f"train+val patients, dates < {(TRAIN_END - GAP).date()}",
                      "alert_line": f"val patients, {TRAIN_END.date()} .. {(TEST_START - GAP).date()}, 5% of quiet days",
                      "test": f"test patients, dates >= {TEST_START.date()}"},
           "train_rows": int(tr.sum()), "test_patients": int(test.patient_id.nunique()), "test_days": int(len(test))}
    for k in ("model", "schedule"):
        res[k] = {"weeks": T.week_metrics(test, f"score_{k}", thr[k]["alert"]),
                  "episodes": {x: v for x, v in T.episode_metrics(test, f"score_{k}", thr[k]["alert"]).items()
                               if x != "lead_days_hist"}}
    res["lift_vs_calendar_ci95"] = T.bootstrap_lift(test, thr)
    res["random_split_reference"] = json.loads((OUT / "metrics.json").read_text())["methods"]["model"]["episodes"]["episode_recall"]
    (OUT / "exp_temporal_holdout.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
