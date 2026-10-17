"""Experiment: do diary notes add to the rough-patch model as inputs? (They are used as a same-day safety flag instead.)

Usage: python -I analysis/exp/notes_features.py      (after analysis/train.py)
Writes: analysis/out/exp_notes_features.json

Same learner, seed, split, label, and 5% alert budget as train.py. Adds the note red-flag categories from
analysis/notes_scan.py as features, under the same leakage guard as the check-ins: what a note SAYS is used up to t-3,
whether a note was written is used up to t. Decision rule, fixed before running: add the notes to the model only if
validation week AUC rises by 0.005 or more AND validation episode recall does not fall.
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
from notes_scan import LEXICON, RED_FLAGS, categories  # noqa: E402

OUT = ROOT / "analysis" / "out"


def note_features(d):
    g = d.patient_id
    cats = d.diary_note.map(categories)
    lag = lambda s: s.groupby(g).shift(T.CHECKIN_LAG)
    roll = lambda s, n: s.astype(float).groupby(g).transform(lambda v: v.rolling(n, min_periods=1).sum())
    N = pd.DataFrame(index=d.index)
    for c in LEXICON:
        N[f"note_{c}_7"] = roll(lag(cats.map(lambda s, c=c: c in s).astype(float)), 7)
    N["note_red_flag_7"] = roll(lag(cats.map(lambda s: bool(s & set(RED_FLAGS))).astype(float)), 7)
    N["note_rate14"] = roll(d.diary_note.notna(), 14) / 14
    return N


def main():
    d = pd.read_parquet(OUT / "scored.parquet")
    F = pd.read_parquet(OUT / "features.parquet")
    assert len(F) == len(d) and (F.index == d.index).all()
    feats = list(F.columns)
    N = note_features(d)
    G = pd.concat([F, N], axis=1)
    use = (d.in_episode == 0) & (d.day_in_program >= 14)
    tr, va = [(use & (d.split == k)).values for k in ("train", "val")]
    y = d.target.values
    fit = lambda cols: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=T.SEED).fit(G.loc[tr, cols], y[tr])
    base = fit(feats)
    d["score_base"] = base.predict_proba(G[feats])[:, 1]
    same = float(np.abs(d.score_base - d.score_model).max())
    d["score_notes"] = fit(feats + list(N.columns)).predict_proba(G[feats + list(N.columns)])[:, 1]
    res = {"refit_matches_served_model_max_abs_diff": same, "note_features": list(N.columns)}
    for k in ("base", "notes"):
        s = d.loc[va, f"score_{k}"]
        thr = float(np.quantile(s, 1 - 0.05))
        res[k] = {}
        for split in ("val", "test"):
            t = d[d.split == split]
            res[k][split] = {"week_auc": T.week_metrics(t, f"score_{k}", thr)["auc"],
                             "episode_recall": T.episode_metrics(t, f"score_{k}", thr)["episode_recall"],
                             "alert_precision": T.episode_metrics(t, f"score_{k}", thr)["alert_precision"]}
    dv = {m: round(res["notes"]["val"][m] - res["base"]["val"][m], 4) for m in ("week_auc", "episode_recall", "alert_precision")}
    res["val_change"] = dv
    res["decision"] = ("add notes to the model" if dv["week_auc"] >= 0.005 and dv["episode_recall"] >= 0
                       else "keep notes out of the model; use them as the same-day safety flag")
    (OUT / "exp_notes_features.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
