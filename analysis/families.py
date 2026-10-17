"""Model-family bake-off, validation patients only (thresholds on the train carve-out). Never reads test.

Usage: python -I analysis/families.py <data dir> <family> [features=main|v2] [task=rough|er]
Families: hgb, lgbm, xgb, rf, et, lrspline, cnn, ens:<a>,<b>[,<c>] (averages cached val scores by rank).
Appends a row to analysis/research_log.md under "Model families"; caches scores in analysis/out/research/fam_*.npy.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research as R  # noqa: E402
import train as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "analysis" / "research_log.md"
SEED = T.SEED


def model(fam, pos_rate):
    if fam == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)
    if fam == "lgbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=200,
                                  colsample_bytree=0.7, subsample=0.8, subsample_freq=1, reg_lambda=1.0,
                                  random_state=SEED, verbose=-1)
    if fam == "xgb":
        import xgboost as xgb
        return xgb.XGBClassifier(n_estimators=600, learning_rate=0.03, max_depth=6, min_child_weight=20,
                                 subsample=0.8, colsample_bytree=0.7, tree_method="hist", random_state=SEED, n_jobs=-1)
    if fam in ("rf", "et"):
        from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
        cls = RandomForestClassifier if fam == "rf" else ExtraTreesClassifier
        return cls(n_estimators=300, min_samples_leaf=50, max_features=0.3, n_jobs=-1, random_state=SEED)
    if fam == "lrspline":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import SplineTransformer
        return make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                             SplineTransformer(n_knots=5, degree=3, extrapolation="constant"),
                             LogisticRegression(C=0.3, max_iter=3000))
    raise ValueError(fam)


V2_EXTRA = ("_z14", "_slope7", "_days60")


def features(fs, d, F):
    """The cached F already holds the v2 columns (14-day trends, 60-day crash memory); "main" drops them (39bc5f8 set)."""
    if fs == "v2":
        return F.copy()
    return F[[c for c in F.columns if not c.endswith(V2_EXTRA)]].copy()


def rows_for(task, d, pts):
    if task == "rough":
        m = (d.in_episode == 0) & (d.day_in_program >= 14)
    else:
        m = (d.day_in_program >= 14) & (d.groupby("patient_id").er.transform(lambda v: v.rolling(7, min_periods=1).sum()) == 0)
    return (m & d.patient_id.isin(pts)).values


def cnn_scores(d, F, task, fit, score_rows):
    """Small 1D-CNN over the last 28 days of per-day wearable z-scores (+ missing mask) and calendar channels."""
    import torch
    from torch import nn
    torch.manual_seed(SEED)
    sig = list(T.SIGNALS)
    g = d.groupby("patient_id")
    ch = []
    for s in sig:
        base = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).median())
        sd = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
        z = ((d[s] - base) / sd).clip(-6, 6)
        ch.append(z.fillna(0).values)
        ch.append(d[s].isna().astype(float).values)
    cl = d.treatment_plan.map(T.cycle_len)
    ch += [d.treatment_today.values.astype(float), F.nadir_window.values.astype(float), F.on_treatment.values.astype(float),
           (d.day_of_cycle.fillna(0) / 28).values, (cl / 28).values, F.iv_chemo.values.astype(float),
           F.radiation.values.astype(float), (F.cycle_number / 12).values, F.day_in_program.values / 9]
    M = np.stack(ch, 1).astype(np.float32)  # rows x C, rows sorted by patient then day
    first = g.cumcount().values  # position within patient
    W = 28

    def windows(idx):
        out = np.zeros((len(idx), M.shape[1], W), np.float32)
        for k in range(W):
            j = idx - (W - 1 - k)
            ok = first[idx] >= (W - 1 - k)
            out[ok, :, k] = M[j[ok]]
        return out

    y = (d.target if task == "rough" else d.er_ahead).values.astype(np.float32)
    tr = np.where(rows_for(task, d, fit))[0]
    rng = np.random.default_rng(SEED)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    C = M.shape[1]
    net = nn.Sequential(nn.Conv1d(C, 64, 5, padding=2), nn.ReLU(), nn.Conv1d(64, 64, 5, padding=2), nn.ReLU(),
                        nn.AdaptiveMaxPool1d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(64, 32), nn.ReLU(),
                        nn.Linear(32, 1)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    pw = torch.tensor([(1 - y[tr].mean()) / max(y[tr].mean(), 1e-4) ** 0.5], device=dev)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    for ep in range(12):
        rng.shuffle(tr)
        for b in range(0, len(tr), 2048):
            idx = tr[b:b + 2048]
            xb = torch.from_numpy(windows(idx)).to(dev)
            yb = torch.from_numpy(y[idx]).to(dev)
            opt.zero_grad()
            loss = lossf(net(xb).squeeze(1), yb)
            loss.backward()
            opt.step()
        print("epoch", ep, float(loss))
    net.eval()
    out = np.zeros(len(score_rows), np.float32)
    with torch.no_grad():
        for b in range(0, len(score_rows), 8192):
            idx = score_rows[b:b + 8192]
            out[b:b + 8192] = torch.sigmoid(net(torch.from_numpy(windows(idx)).to(dev)).squeeze(1)).cpu().numpy()
    return out


def run(fam, fs, task):
    d, F = R.base()
    fit, carve, va = R.splits(d)
    X = features(fs, d, F)
    cols = list(X.columns)
    score_rows = np.where(d.patient_id.isin(carve | va).values)[0]
    cache = R.CACHE / f"fam_{task}_{fs}_{fam}.npy"
    if fam.startswith("ens:"):
        parts = fam[4:].split(",")
        ss = [np.load(R.CACHE / f"fam_{task}_{fs}_{p}.npy") for p in parts]
        s_rows = np.mean([pd.Series(s).rank(pct=True).values for s in ss], 0) * 0.3  # rank average, rescaled
    elif fam == "cnn":
        s_rows = cnn_scores(d, F, task, fit, score_rows)
    else:
        m = rows_for(task, d, fit)
        y = (d.target if task == "rough" else d.er_ahead).values[m].astype(int)
        mdl = model(fam, y.mean())
        Xf = X.loc[m, cols]
        if fam in ("rf", "et", "lrspline"):
            Xf = Xf.fillna(-99) if fam != "lrspline" else Xf
            if fam in ("rf", "et"):
                rs = np.random.default_rng(SEED).choice(len(Xf), min(len(Xf), 200_000), replace=False)
                Xf, y = Xf.iloc[rs], y[rs]
        mdl.fit(Xf, y)
        Xs = X.iloc[score_rows][cols]
        if fam in ("rf", "et"):
            Xs = Xs.fillna(-99)
        s_rows = mdl.predict_proba(Xs)[:, 1]
    np.save(cache, s_rows)
    s = np.full(len(d), np.nan)
    s[score_rows] = s_rows
    d = d.assign(score_x=s)
    cmask = rows_for(task, d, carve)
    vmask = rows_for(task, d, va)
    if task == "rough":
        thr = float(np.quantile(d.score_x.values[cmask], 1 - R.ALERT_RATE))
        v = d[d.patient_id.isin(va)]
        w, e = T.week_metrics(v, "score_x", thr), T.episode_metrics(v, "score_x", thr)
        res = {"val_episode_recall": e["episode_recall"], "val_er_recall": e["er_recall"], "val_week_auc": w["auc"],
               "val_week_precision": w["precision"], "alerts_ppm": e["alerts_per_patient_month"]}
    else:
        thr = float(np.quantile(d.score_x.values[cmask], 0.97))
        yv, sv = d.er_ahead.values[vmask], d.score_x.values[vmask]
        pred = sv >= thr
        # event-level: first ER/admission caught 2..7 days ahead at the 3% budget
        e = T.episode_metrics(d[d.patient_id.isin(va)].assign(in_episode=0), "score_x", thr)
        res = {"val_er_auc": round(float(roc_auc_score(yv, sv)), 3), "val_er_ap": round(float(average_precision_score(yv, sv)), 4),
               "val_day_recall_3pct": round(float(pred[yv == 1].mean()), 3),
               "val_day_precision_3pct": round(float(yv[pred].mean()), 3), "val_er_event_recall": e["er_recall"]}
    res = {"family": fam, "features": fs, "task": task, **res}
    with LOG.open("a") as f:
        if "## Model families" not in LOG.read_text():
            f.write("\n## Model families (validation only; thresholds on train carve-out)\n\n")
        f.write(f"- {json.dumps(res)}\n")
    return res


if __name__ == "__main__":
    t0 = time.time()
    fam = sys.argv[2]
    fs = sys.argv[3] if len(sys.argv) > 3 else "main"
    task = sys.argv[4] if len(sys.argv) > 4 else "rough"
    print(json.dumps(run(fam, fs, task)), round(time.time() - t0, 1), "s")
