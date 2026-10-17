"""Bad Week Radar forecaster: label rough patches, build wearable-only features, fit, evaluate, export.

Usage: .venv/bin/python -I analysis/train.py <path to Challenge3_Bad_Week_Radar>
Writes: analysis/out/metrics.json and src/data/{model,survivors}.json (served by the Worker).

Inputs to the model are wearable signals, wear time and the known treatment schedule only.
Self-reports (daily feeling, weekly symptoms, diary notes) and the events column define the label and
are never used as inputs: the point is to warn before the person says anything.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]).expanduser() / "synthetic_data" if len(sys.argv) > 1 else None
OUT = ROOT / "analysis" / "out"
DATA = ROOT / "src" / "data"
HORIZON = 7  # predict an onset within the next 7 days
MIN_LEAD = 2  # an alert counts as early warning only if it fires at least 2 days before onset
SEED = 7

SIGNALS = {
    "steps": "Steps",
    "active_minutes": "Active minutes",
    "resting_heart_rate": "Resting heart rate",
    "hrv_rmssd_ms": "Heart rate variability",
    "sleep_minutes": "Sleep",
    "sleep_efficiency_pct": "Sleep efficiency",
    "times_woke_up": "Night wakings",
    "skin_temp_change_c": "Skin temperature",
    "minutes_watch_worn": "Watch wear time",
}
CLINICAL = "ER visit|admitted to hospital|treatment paused"


def load():
    d = pd.read_csv(SRC / "synthetic_daily.csv", parse_dates=["date"])
    p = pd.read_csv(SRC / "synthetic_patients.csv")
    d = d.merge(p[["patient_id", "treatment_plan", "device", "cancer_type", "stage", "age", "sex",
                   "race_ethnicity", "preferred_language", "lives_alone"]], on="patient_id")
    return d.sort_values(["patient_id", "day_in_program"]).reset_index(drop=True), p


def label(d):
    """Rough day = feeling <= 2, weekly fatigue >= 3, or ER / admission / treatment paused.
    Patch day = rough day with another rough day within 3 days, or any clinical event (one bad day is not a patch).
    Onset = first patch day after 7 quiet days. Episode = onset .. last patch day, gaps under 7 days."""
    ev = d.events.fillna("")
    d["clinical"] = ev.str.contains(CLINICAL).astype(int)
    d["er"] = ev.str.contains("ER visit|admitted to hospital").astype(int)
    d["rough"] = ((d.daily_feeling_1_to_5 <= 2) | (d.weekly_fatigue_0_to_4 >= 3) | (d.clinical == 1)).astype(int)
    g = d.groupby("patient_id")
    ahead = g.rough.transform(lambda s: s[::-1].rolling(4, min_periods=1).sum()[::-1])
    d["patch"] = ((d.rough == 1) & ((ahead >= 2) | (d.clinical == 1))).astype(int)
    quiet = g.patch.transform(lambda s: s.rolling(7, min_periods=1).sum().shift(1).fillna(0))
    d["onset"] = ((d.patch == 1) & (quiet == 0)).astype(int)
    # in_episode: from onset until 7 days after the last patch day of that run
    recent = g.patch.transform(lambda s: s.rolling(7, min_periods=1).sum())
    d["in_episode"] = (recent > 0).astype(int)
    # target at day t: an onset in t+1 .. t+HORIZON
    d["target"] = g.onset.transform(
        lambda s: s[::-1].rolling(HORIZON, min_periods=1).sum()[::-1].shift(-1).fillna(0)).clip(0, 1).astype(int)
    d["days_to_onset"] = g.onset.transform(_days_to_next)
    d["er_ahead"] = g.er.transform(
        lambda s: s[::-1].rolling(HORIZON, min_periods=1).sum()[::-1].shift(-1).fillna(0)).clip(0, 1)
    return d


def _days_to_next(s):
    idx = np.where(s.values == 1)[0]
    out = np.full(len(s), np.nan)
    j = 0
    for i in range(len(s)):
        while j < len(idx) and idx[j] <= i:
            j += 1
        if j < len(idx):
            out[i] = idx[j] - i
    return pd.Series(out, index=s.index)


def cycle_len(plan):
    for k, v in {"every 21": 21, "every 14": 14, "weekly": 7, "2 weeks on 1": 21, "3 weeks on 1": 28}.items():
        if k in plan:
            return v
    return 0


def features(d):
    g = d.groupby("patient_id")
    f = pd.DataFrame(index=d.index)
    for s in SIGNALS:
        x = d[s]
        # personal baseline: days t-35 .. t-8 (excludes the last week, so a slow slide still shows)
        base = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).median())
        spread = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
        r3 = g[s].transform(lambda v: v.rolling(3, min_periods=1).mean())
        r7 = g[s].transform(lambda v: v.rolling(7, min_periods=2).mean())
        f[f"{s}_z3"] = ((r3 - base) / spread).clip(-6, 6)
        f[f"{s}_z7"] = ((r7 - base) / spread).clip(-6, 6)
        if s == "skin_temp_change_c":
            f[f"{s}_max3"] = g[s].transform(lambda v: v.rolling(3, min_periods=1).max())
    f["watch_off_days7"] = g.steps.transform(lambda v: v.isna().rolling(7, min_periods=1).sum())
    f["watch_worn_z7"] = f.pop("minutes_watch_worn_z7")
    f["low_wear_days7"] = g.minutes_watch_worn.transform(lambda v: (v < 600).rolling(7, min_periods=1).sum())
    # known schedule
    cl = d.treatment_plan.map(cycle_len)
    doc = d.day_of_cycle
    f["on_treatment"] = (d.treatment_phase == "on treatment").astype(int)
    f["cyclic"] = (cl > 0).astype(int)
    f["days_since_dose"] = doc.fillna(0)
    f["nadir_window"] = ((doc >= 1) & (doc <= 6)).astype(int)  # days 1-6 after a dose
    f["dose_soon"] = (((cl - doc) >= 0) & ((cl - doc) <= 5) & (cl > 0)).astype(int)
    f["cycle_number"] = d.treatment_cycle.fillna(0).clip(0, 12)
    f["radiation"] = d.treatment_plan.str.contains("adiation").astype(int)
    f["iv_chemo"] = d.treatment_plan.str.contains("IV chemo|Chemoradiation").astype(int)
    f["day_in_program"] = d.day_in_program.clip(0, 270) / 30
    # model v2 (picked on validation patients, see analysis/research_log.md):
    # 14-day level and 7-day slope vs personal baseline, and a 60-day memory of past wearable crashes
    for s in ["steps", "resting_heart_rate", "hrv_rmssd_ms", "sleep_minutes", "sleep_efficiency_pct", "minutes_watch_worn"]:
        base = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).median())
        sd = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
        r14 = g[s].transform(lambda v: v.rolling(14, min_periods=4).mean())
        f[f"{s}_z14"] = ((r14 - base) / sd).clip(-6, 6)
        f[f"{s}_slope7"] = g[s].transform(lambda v: v.rolling(7, min_periods=4).apply(_slope, raw=True)) / sd
    f["steps_crash_days60"] = (f["steps_z3"] < -1.5).astype(int).groupby(d.patient_id).transform(
        lambda v: v.rolling(60, min_periods=1).sum())
    f["rhr_high_days60"] = (f["resting_heart_rate_z3"] > 1.5).astype(int).groupby(d.patient_id).transform(
        lambda v: v.rolling(60, min_periods=1).sum())
    return f


def _slope(v):
    m = ~np.isnan(v)
    if m.sum() < 4:
        return np.nan
    return np.polyfit(np.arange(len(v))[m], v[m], 1)[0]


SCHEDULE = ["on_treatment", "cyclic", "days_since_dose", "nadir_window", "dose_soon", "cycle_number",
            "radiation", "iv_chemo", "day_in_program"]


def fit_lr(X, y):
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = ((X - mu) / sd).fillna(0)
    m = LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced").fit(Z, y)
    return m, mu, sd


def lr_score(m, mu, sd, X):
    return m.predict_proba(((X - mu) / sd).fillna(0))[:, 1]


def episode_metrics(df, score_col, thr):
    """Episode-level: recall = onsets with an alert in [onset-7, onset-MIN_LEAD]; lead = onset - first alert day.
    Alert precision = alert runs (first alert day after 3 quiet days) followed by an onset within 7 days."""
    rec, leads, er_hit, er_n, runs, good_runs, months = 0, [], 0, 0, 0, 0, 0.0
    n_on = 0
    for _, p in df.groupby("patient_id"):
        a = ((p[score_col].values >= thr) & (p.in_episode.values == 0)).astype(int)
        on = p.onset.values
        er = p.er.values
        months += len(p) / 30.4
        for i in np.where(on == 1)[0]:
            if i < 14:
                continue
            n_on += 1
            start = max(0, i - HORIZON)
            w = a[start: i - MIN_LEAD + 1]
            if w.any():
                rec += 1
                leads.append(i - (start + int(np.argmax(w))))
        er_first = [i for i in np.where(er == 1)[0] if i >= 14 and not er[max(0, i - 7):i].any()]
        for i in er_first:
            er_n += 1
            if a[max(0, i - HORIZON): i - MIN_LEAD + 1].any():
                er_hit += 1
        starts = [i for i in range(len(a)) if a[i] and not a[max(0, i - 3):i].any()]
        for i in starts:
            runs += 1
            if on[i + 1: i + 1 + HORIZON].any() or p.in_episode.values[i + 1: i + 1 + HORIZON].any():
                good_runs += 1
    return {
        "episodes": n_on,
        "episode_recall": round(rec / max(n_on, 1), 3),
        "median_lead_days": float(np.median(leads)) if leads else None,
        "lead_days_hist": {str(k): int(v) for k, v in pd.Series(leads).value_counts().sort_index().items()},
        "er_admissions": er_n,
        "er_recall": round(er_hit / max(er_n, 1), 3),
        "alert_runs": runs,
        "alert_precision": round(good_runs / max(runs, 1), 3),
        "alerts_per_patient_month": round(runs / max(months, 1), 2),
    }


def week_metrics(df, score_col, thr):
    """Held-out weeks: score on the last day of each patient-week, target = patch onset in the next 7 days."""
    w = df[(df.day_in_program % 7 == 0) & (df.in_episode == 0) & (df.day_in_program >= 14)]
    y, s = w.target.values, w[score_col].values
    pred = s >= thr
    tp = int((pred & (y == 1)).sum())
    return {
        "weeks": int(len(w)), "rough_weeks": int(y.sum()),
        "auc": round(float(roc_auc_score(y, s)), 3),
        "precision": round(tp / max(int(pred.sum()), 1), 3),
        "recall": round(tp / max(int(y.sum()), 1), 3),
        "alert_share": round(float(pred.mean()), 3),
    }


def calibration(df, score_col, bins=10):
    """Predicted vs observed 7-day onset rate on scored held-out days, by risk decile; plus Brier score."""
    q = df[(df.in_episode == 0) & (df.day_in_program >= 14)]
    s, y = q[score_col].values, q.target.values
    edges = np.unique(np.quantile(s, np.linspace(0, 1, bins + 1)))
    b = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, len(edges) - 2)
    rows = [{"predicted": round(float(s[b == i].mean()), 4), "observed": round(float(y[b == i].mean()), 4),
             "days": int((b == i).sum())} for i in range(len(edges) - 1) if (b == i).any()]
    return {"brier": round(float(np.mean((s - y) ** 2)), 4), "base_rate": round(float(y.mean()), 4),
            "brier_if_base_rate": round(float(np.mean((y.mean() - y) ** 2)), 4), "deciles": rows}


def subgroups(df, score_col, thr):
    """Week-level AUC / recall / precision per subgroup; groups with < 30 rough weeks are marked too small."""
    df = df.assign(age_group=pd.cut(df.age, [0, 49, 64, 120], labels=["under 50", "50-64", "65+"]).astype(str))
    out = {}
    for col in ("age_group", "sex", "race_ethnicity", "preferred_language", "cancer_type", "device", "lives_alone"):
        rows = []
        for v, g in df.groupby(col):
            w = g[(g.day_in_program % 7 == 0) & (g.in_episode == 0) & (g.day_in_program >= 14)]
            pos = int(w.target.sum())
            row = {"group": str(v), "patients": int(g.patient_id.nunique()), "rough_weeks": pos}
            if pos >= 30 and pos < len(w):
                pred = w[score_col] >= thr
                tp = int((pred & (w.target == 1)).sum())
                row.update(auc=round(float(roc_auc_score(w.target, w[score_col])), 3),
                           recall=round(tp / pos, 3), precision=round(tp / max(int(pred.sum()), 1), 3))
            else:
                row["note"] = "too few rough weeks to judge"
            rows.append(row)
        out[col] = rows
    return out


def _patient_hits(df, score_col, thr):
    """Per patient: [onsets, caught early, ER/admissions, ER caught] with the episode_metrics rules."""
    res = []
    for _, p in df.groupby("patient_id"):
        a = ((p[score_col].values >= thr) & (p.in_episode.values == 0)).astype(int)
        on, er = p.onset.values, p.er.values
        o = [i for i in np.where(on == 1)[0] if i >= 14]
        e = [i for i in np.where(er == 1)[0] if i >= 14 and not er[max(0, i - 7):i].any()]
        hit = lambda i: a[max(0, i - HORIZON): i - MIN_LEAD + 1].any()
        res.append([len(o), sum(hit(i) for i in o), len(e), sum(hit(i) for i in e)])
    return np.array(res, dtype=float)


def bootstrap_lift(df, thr, reps=1000):
    """95% CI (resampling held-out patients) for Radar minus schedule-only, episode recall and ER recall."""
    m = _patient_hits(df, "score_model", thr["model"]["alert"])
    s = _patient_hits(df, "score_schedule", thr["schedule"]["alert"])
    rng = np.random.default_rng(SEED)
    ep, er = [], []
    for _ in range(reps):
        i = rng.integers(0, len(m), len(m))
        mm, ss = m[i].sum(0), s[i].sum(0)
        ep.append(mm[1] / mm[0] - ss[1] / ss[0])
        er.append(mm[3] / max(mm[2], 1) - ss[3] / max(ss[2], 1))
    ci = lambda v: [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]
    return {"episode_recall_diff": ci(ep), "er_recall_diff": ci(er), "reps": reps, "unit": "patients"}


def main():
    d, patients = load()
    d = label(d)
    F = features(d)
    feats = list(F.columns)
    pids = np.array(sorted(d.patient_id.unique()))
    rng = np.random.default_rng(SEED)
    rng.shuffle(pids)
    n = len(pids)
    split = {p: "train" for p in pids[: int(n * 0.6)]}
    split.update({p: "val" for p in pids[int(n * 0.6): int(n * 0.75)]})
    split.update({p: "test" for p in pids[int(n * 0.75):]})
    d["split"] = d.patient_id.map(split)
    use = (d.in_episode == 0) & (d.day_in_program >= 14)
    tr, va, te = [(use & (d.split == k)).values for k in ("train", "val", "test")]
    y = d.target.values

    m, mu, sd = fit_lr(F[tr], y[tr])
    d["score_logistic"] = lr_score(m, mu, sd, F)
    # schedule baseline: the same learner, given only the treatment calendar (what a coach already knows)
    gs = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)
    d["score_schedule"] = gs.fit(F.loc[tr, SCHEDULE], y[tr]).predict_proba(F[SCHEDULE])[:, 1]
    gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)
    gb.fit(F[tr], y[tr])
    d["score_model"] = gb.predict_proba(F)[:, 1]
    # naive rule a coach could eyeball: the bigger the 3-day steps drop below personal baseline, the higher the score
    d["score_steps_rule"] = (-F["steps_z3"]).fillna(0)

    # thresholds set on validation patients, at a matched alert budget (share of quiet days that alert)
    ALERT_RATE, WATCH_RATE = 0.12, 0.25
    thr = {}
    for k in ("model", "schedule", "logistic", "steps_rule"):
        s = d.loc[va, f"score_{k}"]
        thr[k] = {"alert": float(np.quantile(s, 1 - ALERT_RATE)), "watch": float(np.quantile(s, 1 - WATCH_RATE))}

    test = d[(d.split == "test")]
    report = {"definition": {
        "rough_day": "daily feeling <= 2, OR weekly fatigue >= 3, OR ER visit / hospital admission / treatment paused",
        "rough_patch": "a rough day followed by another within 3 days, or any clinical event; onset = first patch day after 7 quiet days",
        "forecast": f"each evening, P(rough patch onset in the next {HORIZON} days); days already inside a patch are not scored",
        "early_warning": f"an alert counts only if it fires {MIN_LEAD}+ days before onset",
        "inputs": "wearable signals vs personal baseline, wear time, known treatment schedule. No self-reports, no events.",
        "split": "by patient: 60% train, 15% validation (thresholds), 25% test (all numbers below)",
        "alert_budget": f"thresholds put {int(ALERT_RATE*100)}% of quiet validation days on alert, same budget for every method",
    }, "counts": {"patients": int(n), "test_patients": int((pd.Series(split) == 'test').sum()),
                  "onsets_total": int(d.onset.sum()), "label_missing_feeling_share": round(float(d.daily_feeling_1_to_5.isna().mean()), 3)},
        "methods": {}}
    names = {"steps_rule": "Baseline: steps drop", "schedule": "Baseline: treatment schedule only (same learner)",
             "logistic": "Logistic, wearable + schedule (comparison)", "model": "Radar (gradient boosting, wearable + schedule)"}
    for k, nm in names.items():
        report["methods"][k] = {"name": nm, "weeks": week_metrics(test, f"score_{k}", thr[k]["alert"]),
                                "episodes": episode_metrics(test, f"score_{k}", thr[k]["alert"])}
        print(nm, json.dumps(report["methods"][k]))

    report["calibration"] = {k: calibration(test, f"score_{k}") for k in ("model", "schedule")}
    report["subgroups"] = subgroups(test, "score_model", thr["model"]["alert"])
    report["lift_vs_schedule_ci95"] = bootstrap_lift(test, thr)
    print(json.dumps({k: report[k] for k in ("calibration", "lift_vs_schedule_ci95")}))

    # global drivers: permutation importance on test patients (AUC drop)
    from sklearn.inspection import permutation_importance
    sample = d[te].sample(40000, random_state=SEED)
    pi = permutation_importance(gb, F.loc[sample.index], sample.target, scoring="roc_auc", n_repeats=3,
                                random_state=SEED)
    imp = pd.Series(pi.importances_mean, index=feats).sort_values(ascending=False)
    report["feature_importance_auc_drop"] = {k: round(float(v), 4) for k, v in imp.head(15).items()}
    print(imp.head(15))
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(report, indent=2))
    import pickle
    (OUT / "gbm.pkl").write_bytes(pickle.dumps({"model": gb, "schedule_model": gs, "features": feats, "thresholds": thr["model"]}))
    d.to_parquet(OUT / "scored.parquet")
    F.to_parquet(OUT / "features.parquet")
    print("wrote", OUT / "metrics.json")


if __name__ == "__main__":
    main()
