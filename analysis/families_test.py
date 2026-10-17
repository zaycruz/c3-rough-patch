"""ONE test evaluation for the bake-off winner (ER task): ens(hgb,xgb,rf) on v2 features vs HistGB (main, v2).
Fit on train-fit patients, 3% day threshold on the train carve-out, metrics on TEST patients."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
sys.path.insert(0, str(Path(__file__).resolve().parent))
import research as R
import train as T
import families as FAM

d, F = R.base()
fit, carve, va = R.splits(d)
test = set(d.patient_id.unique()) - fit - carve - va
rows = np.where(d.patient_id.isin(carve | test).values)[0]
m = FAM.rows_for("er", d, fit)
y = d.er_ahead.values[m].astype(int)


def scores(fam, fs):
    X = FAM.features(fs, d, F)
    mdl = FAM.model(fam, y.mean())
    Xf, yy = X.loc[m], y
    if fam == "rf":
        rs = np.random.default_rng(T.SEED).choice(len(Xf), min(len(Xf), 200_000), replace=False)
        Xf, yy = Xf.iloc[rs].fillna(-99), y[rs]
    mdl.fit(Xf, yy)
    Xs = X.iloc[rows]
    return mdl.predict_proba(Xs.fillna(-99) if fam == "rf" else Xs)[:, 1]


out = {}
cand = {"hgb main": scores("hgb", "main"), "hgb v2": scores("hgb", "v2")}
parts = [cand["hgb v2"], scores("xgb", "v2"), scores("rf", "v2")]
cand["ens hgb+xgb+rf v2"] = np.mean([pd.Series(s).rank(pct=True).values for s in parts], 0)
for name, s_rows in cand.items():
    s = np.full(len(d), np.nan)
    s[rows] = s_rows
    dd = d.assign(score_x=s)
    thr = float(np.quantile(dd.score_x.values[FAM.rows_for("er", dd, carve)], 0.97))
    tm = FAM.rows_for("er", dd, test)
    yv, sv = dd.er_ahead.values[tm], dd.score_x.values[tm]
    pred = sv >= thr
    e = T.episode_metrics(dd[dd.patient_id.isin(test)].assign(in_episode=0), "score_x", thr)
    out[name] = {"test_er_auc": round(float(roc_auc_score(yv, sv)), 3), "test_er_ap": round(float(average_precision_score(yv, sv)), 4),
                 "test_day_recall_3pct": round(float(pred[yv == 1].mean()), 3), "test_day_precision_3pct": round(float(yv[pred].mean()), 3),
                 "test_er_event_recall_2to7d": e["er_recall"], "test_er_events": e["er_admissions"]}
    print(name, json.dumps(out[name]))
with (Path(__file__).resolve().parent / "research_log.md").open("a") as f:
    f.write("\n### One test evaluation (ER task, winner vs HistGB)\n\n")
    for k, v in out.items():
        f.write(f"- {k}: {json.dumps(v)}\n")
