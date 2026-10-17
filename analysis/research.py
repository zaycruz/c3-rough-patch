"""Validation-only experiment harness for the Radar model. Never reads test metrics.

Usage: python -I analysis/research.py <data dir> <experiment name> [...]
Fits on train patients minus a 20% threshold carve-out, sets the 12% alert threshold on the carve-out,
and reports metrics on validation patients. Appends one row per experiment to analysis/research_log.md.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train as T  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "analysis" / "out" / "research"
LOG = ROOT / "analysis" / "research_log.md"
ALERT_RATE = 0.12


def base():
    CACHE.mkdir(parents=True, exist_ok=True)
    if (CACHE / "d.parquet").exists():
        return pd.read_parquet(CACHE / "d.parquet"), pd.read_parquet(CACHE / "F.parquet")
    d, _ = T.load()
    d = T.label(d)
    F = T.features(d)
    d.to_parquet(CACHE / "d.parquet")
    F.to_parquet(CACHE / "F.parquet")
    return d, F


def splits(d):
    pids = np.array(sorted(d.patient_id.unique()))
    rng = np.random.default_rng(T.SEED)
    rng.shuffle(pids)
    n = len(pids)
    tr, va = pids[: int(n * 0.6)], pids[int(n * 0.6): int(n * 0.75)]
    carve = set(tr[: int(len(tr) * 0.2)])
    fit = set(tr) - carve
    import os
    if os.environ.get("C3_SWAP"):  # second opinion: thresholds on val, metrics on the carve-out (still never test)
        return fit, set(va), carve
    return fit, carve, set(va)


def extra(name, d, F):
    """Extra feature blocks, cached. All use data up to day t only."""
    path = CACHE / f"x_{name}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    g = d.groupby("patient_id")
    X = pd.DataFrame(index=d.index)
    if name == "trend14":
        for s in ["steps", "resting_heart_rate", "hrv_rmssd_ms", "sleep_minutes", "sleep_efficiency_pct", "minutes_watch_worn"]:
            base = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).median())
            sd = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
            r14 = g[s].transform(lambda v: v.rolling(14, min_periods=4).mean())
            X[f"{s}_z14"] = ((r14 - base) / sd).clip(-6, 6)
            # slope of last 7 days (per day, in sd units)
            X[f"{s}_slope7"] = g[s].transform(
                lambda v: v.rolling(7, min_periods=4).apply(_slope, raw=True)) / sd
    elif name == "prevcycle":
        # same-phase memory: steps / RHR / sleep-eff deviations at the same day_of_cycle in the previous cycle,
        # and the worst dip of the previous cycle's days 1-7 (all already observed by day t)
        cl = d.treatment_plan.map(T.cycle_len)
        for s in ["steps", "resting_heart_rate", "sleep_efficiency_pct", "hrv_rmssd_ms"]:
            z = F[f"{s}_z3"]
            out = np.full(len(d), np.nan)
            out_min = np.full(len(d), np.nan)
            for pid, idx in g.indices.items():
                c = int(cl.iloc[idx[0]])
                if c <= 0:
                    continue
                zz = z.values[idx]
                lag = np.full(len(idx), np.nan)
                lag[c:] = zz[:-c] if len(idx) > c else lag[c:]
                # lookahead within last cycle: same phase +1..+5 days from last cycle (still in the past when c>5)
                ahead = np.full(len(idx), np.nan)
                ser = pd.Series(zz)
                fwd = ser[::-1].rolling(6, min_periods=1).min()[::-1].values if s in ("steps", "sleep_efficiency_pct", "hrv_rmssd_ms") \
                    else ser[::-1].rolling(6, min_periods=1).max()[::-1].values
                ahead[c:] = fwd[:-c] if len(idx) > c else ahead[c:]
                out[idx] = lag
                out_min[idx] = ahead
            X[f"{s}_prevcyc"] = out
            X[f"{s}_prevcyc_next6"] = out_min
    elif name == "engage":
        off = d.steps.isna().astype(int)
        X["watch_off_days14"] = off.groupby(d.patient_id).transform(lambda v: v.rolling(14, min_periods=1).sum())
        X["watch_off_streak"] = off.groupby(d.patient_id).transform(
            lambda v: v.groupby((v != v.shift()).cumsum()).cumsum() * v)
        X["wear_trend28"] = g.minutes_watch_worn.transform(
            lambda v: v.rolling(7, min_periods=3).mean() - v.shift(7).rolling(21, min_periods=7).mean())
    elif name == "inter":
        X["skin_x_rhr"] = F["skin_temp_change_c_max3"].fillna(0) * F["resting_heart_rate_z3"].fillna(0)
        X["hrv_x_rhr"] = -F["hrv_rmssd_ms_z3"].fillna(0) * F["resting_heart_rate_z3"].fillna(0)
        X["steps_x_sleep"] = -F["steps_z3"].fillna(0) * -F["sleep_efficiency_pct_z3"].fillna(0)
        cl = d.treatment_plan.map(T.cycle_len)
        X["days_to_next_dose"] = np.where(cl > 0, cl - d.day_of_cycle.fillna(0) + 1, np.nan)
    elif name == "phase":
        # deviation vs the person's own past values at the same cycle phase (expanding mean over earlier cycles)
        for s in ["steps", "resting_heart_rate", "sleep_efficiency_pct"]:
            key = d.patient_id + "_" + d.day_of_cycle.fillna(-1).astype(int).astype(str)
            past = d.groupby(key)[s].transform(lambda v: v.shift(1).expanding(min_periods=1).mean())
            sd = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
            r3 = g[s].transform(lambda v: v.rolling(3, min_periods=1).mean())
            X[f"{s}_vs_phase"] = ((r3 - past) / sd).clip(-6, 6).where(d.day_of_cycle.notna())
    elif name == "history":
        # wearable-derived memory of past crashes: count of days in the past 60 with steps_z3 < -1.5
        crash = (F["steps_z3"] < -1.5).astype(int)
        X["steps_crash_days60"] = crash.groupby(d.patient_id).transform(lambda v: v.rolling(60, min_periods=1).sum())
        X["rhr_high_days60"] = (F["resting_heart_rate_z3"] > 1.5).astype(int).groupby(d.patient_id).transform(
            lambda v: v.rolling(60, min_periods=1).sum())
    else:
        raise ValueError(name)
    X.to_parquet(path)
    return X


def _slope(v):
    m = ~np.isnan(v)
    if m.sum() < 4:
        return np.nan
    x = np.arange(len(v))[m]
    return np.polyfit(x, v[m], 1)[0]


def evaluate(d, F, cols, params=None, label="", er_blend=0.0):
    fit, carve, va = splits(d)
    use = (d.in_episode == 0) & (d.day_in_program >= 14)
    mfit = (use & d.patient_id.isin(fit)).values
    y = d.target.values
    p = dict(max_iter=300, learning_rate=0.05, random_state=T.SEED)
    p.update(params or {})
    gb = HistGradientBoostingClassifier(**p).fit(F.loc[mfit, cols], y[mfit])
    rows = d.patient_id.isin(carve | va).values
    s = np.full(len(d), np.nan)
    s[rows] = gb.predict_proba(F.loc[rows, cols])[:, 1]
    if er_blend:
        use2 = (d.day_in_program >= 14) & (d.groupby("patient_id").er.transform(lambda v: v.rolling(7, min_periods=1).sum()) == 0)
        m2 = (use2 & d.patient_id.isin(fit)).values
        ge = HistGradientBoostingClassifier(**p).fit(F.loc[m2, cols], d.er_ahead.values[m2])
        pe = ge.predict_proba(F.loc[rows, cols])[:, 1]
        # rank-blend so the scale stays a probability-like 0..1
        s[rows] = (1 - er_blend) * s[rows] + er_blend * pe * (np.nanmean(s[rows]) / max(pe.mean(), 1e-6))
    d = d.assign(score_x=s)
    cmask = (use & d.patient_id.isin(carve)).values
    thr = float(np.quantile(d.loc[cmask, "score_x"], 1 - ALERT_RATE))
    v = d[d.patient_id.isin(va)]
    w = T.week_metrics(v, "score_x", thr)
    e = T.episode_metrics(v, "score_x", thr)
    res = {"label": label, "val_episode_recall": e["episode_recall"], "val_er_recall": e["er_recall"],
           "val_week_auc": w["auc"], "val_week_precision": w["precision"], "val_week_recall": w["recall"],
           "alerts_ppm": e["alerts_per_patient_month"], "alert_precision": e["alert_precision"]}
    return res


def log(res, kept=""):
    if not LOG.exists():
        LOG.write_text("# Radar research log (validation patients only; thresholds on a train carve-out)\n\n"
                       "| # | idea | val ep. recall | val ER recall | val week AUC | val week precision | val week recall | alerts/pt/mo | kept? |\n"
                       "|---|---|---|---|---|---|---|---|---|\n")
    n = LOG.read_text().count("\n| ") - 1
    with LOG.open("a") as f:
        f.write(f"| {n} | {res['label']} | {res['val_episode_recall']} | {res['val_er_recall']} | {res['val_week_auc']} | "
                f"{res['val_week_precision']} | {res['val_week_recall']} | {res['alerts_ppm']} | {kept} |\n")


if __name__ == "__main__":
    t0 = time.time()
    d, F = base()
    print("base loaded", round(time.time() - t0, 1), "s")
    blocks = [b for b in sys.argv[2].split("+") if b and b != "base"]
    params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    er_blend = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    X = F.copy()
    for b in blocks:
        X = X.join(extra(b, d, F))
    import os
    label = ("[swap] " if os.environ.get("C3_SWAP") else "") + sys.argv[2] + (f" {json.dumps(params)}" if params else "") + (f" er_blend={er_blend}" if er_blend else "")
    if params and params.pop("_schedule_only", False):
        cols = T.SCHEDULE
    else:
        cols = list(X.columns)
    res = evaluate(d, X, cols, params, label, er_blend)
    print(json.dumps(res))
    log(res)
    print("done", round(time.time() - t0, 1), "s")
