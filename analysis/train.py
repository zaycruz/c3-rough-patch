"""Bad Week Radar forecaster: label rough patches, build wearable-only features, fit, evaluate, export.

Usage: .venv/bin/python -I analysis/train.py <path to Challenge3_Bad_Week_Radar>
Writes: analysis/out/metrics.json and src/data/{model,survivors}.json (served by the Worker).

Inputs to the model are wearable signals, wear time and the known treatment schedule only.
Self-reports (daily feeling, weekly symptoms, diary notes) and the events column define the label and
are never used as inputs: the point is to warn before the person says anything.
"""
import json
import os
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
URGENT_RATE = 0.03  # share of quiet validation days flagged urgent
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


SYMPTOMS = ["weekly_fatigue_0_to_4", "weekly_nausea_0_to_4", "weekly_pain_0_to_4", "weekly_appetite_loss_0_to_4",
            "weekly_diarrhea_0_to_4", "weekly_trouble_sleeping_0_to_4", "weekly_anxiety_0_to_4", "weekly_sadness_0_to_4"]
LABEL_VERSION = os.environ.get("C3_LABEL", "v2")


def episodes(d, rough, sfx=""):
    """From a 0/1 rough-day series: patch day = rough day with another rough day within 3 days, or any clinical event
    (one bad day is not a patch). Onset = first patch day after 7 quiet days. in_episode = within 7 days of a patch day.
    target at day t = an onset in t+1 .. t+HORIZON."""
    g = rough.groupby(d.patient_id)
    ahead = g.transform(lambda s: s[::-1].rolling(4, min_periods=1).sum()[::-1])
    patch = ((rough == 1) & ((ahead >= 2) | (d.clinical == 1))).astype(int)
    gp = patch.groupby(d.patient_id)
    quiet = gp.transform(lambda s: s.rolling(7, min_periods=1).sum().shift(1).fillna(0))
    onset = ((patch == 1) & (quiet == 0)).astype(int)
    d[f"patch{sfx}"], d[f"onset{sfx}"] = patch, onset
    d[f"in_episode{sfx}"] = (gp.transform(lambda s: s.rolling(7, min_periods=1).sum()) > 0).astype(int)
    d[f"target{sfx}"] = onset.groupby(d.patient_id).transform(
        lambda s: s[::-1].rolling(HORIZON, min_periods=1).sum()[::-1].shift(-1).fillna(0)).clip(0, 1).astype(int)


def label(d):
    """v1 label (kept for comparison): rough day = feeling <= 2, weekly fatigue >= 3, or ER / admission / pause."""
    ev = d.events.fillna("")
    d["clinical"] = ev.str.contains(CLINICAL).astype(int)
    d["er"] = ev.str.contains("ER visit|admitted to hospital").astype(int)
    d["rough_v1"] = ((d.daily_feeling_1_to_5 <= 2) | (d.weekly_fatigue_0_to_4 >= 3) | (d.clinical == 1)).astype(int)
    episodes(d, d.rough_v1, "_v1")
    g = d.groupby("patient_id")
    d["er_ahead"] = g.er.transform(
        lambda s: s[::-1].rolling(HORIZON, min_periods=1).sum()[::-1].shift(-1).fillna(0)).clip(0, 1)
    return d


def _personal_base(d, col, min_obs, window=28):
    """Median of this person's previous reports of col (past reports only, not past days)."""
    def per(s):
        r = s.dropna()
        return r.shift(1).rolling(window, min_periods=min_obs).median().reindex(s.index).ffill()
    return d.groupby("patient_id")[col].transform(per)


def _skip_streak(miss):
    out, c = [], 0
    for v in miss:
        out.append(c)
        c = c + 1 if v else 0
    return out


NOWCAST = ["steps", "active_minutes", "resting_heart_rate", "hrv_rmssd_ms", "sleep_minutes", "sleep_efficiency_pct",
           "times_woke_up", "skin_temp_change_c", "minutes_watch_worn"]


def label_v2(d, train_mask):
    """v2 label. Rough day =
    - self-report, relative to the person: feeling 1, OR feeling >= 2 points below their own median of the previous
      28 check-ins (needs 5; until then feeling <= 2), OR on the weekly check-in any of 8 symptoms >= 3 or >= 2 above
      their own median of previous weekly check-ins;
    - OR a clinical event (ER visit, admission, treatment paused);
    - OR, on a day with no daily check-in, the quantitative stand-in: a same-day wearable nowcast of P(rough self-report),
      trained on check-in days of train patients only, with the run of skipped check-ins as an input, so every extra
      skipped day raises the weight. A missing check-in AND watch off (< 10 h worn) is unknown, not rough."""
    feel = d.daily_feeling_1_to_5
    fbase = _personal_base(d, "daily_feeling_1_to_5", 5)
    feel_rough = (feel <= 1) | (fbase.notna() & (fbase - feel >= 2)) | (fbase.isna() & (feel <= 2))
    sym_rough = pd.Series(False, index=d.index)
    for c in SYMPTOMS:
        sb = _personal_base(d, c, 2, window=8)
        sym_rough |= (d[c] >= 3) | (sb.notna() & (d[c] - sb >= 2))
    d["rough_self"] = (feel_rough | sym_rough).astype(int)
    miss = feel.isna()
    d["skips_before"] = np.concatenate([_skip_streak(m) for _, m in miss.groupby(d.patient_id)])
    # same-day signals vs the person's own baseline (days t-35..t-8): independent of the forecaster's trend features
    X = pd.DataFrame(index=d.index)
    g = d.groupby("patient_id")
    for s in NOWCAST:
        b = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).median())
        sd = g[s].transform(lambda v: v.shift(8).rolling(28, min_periods=7).std()).clip(lower=1e-3)
        X[s] = ((d[s] - b) / sd).clip(-6, 6)
    X["skip_run"] = np.where(miss, d.skips_before + 1, d.skips_before)  # a missed day counts itself
    obs = (~miss & train_mask).values
    nm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=SEED)
    nm.fit(X[obs], feel_rough[obs].astype(int))
    p = nm.predict_proba(X)[:, 1]
    unknown = miss & (d.minutes_watch_worn < 600)
    cand = (miss & ~unknown).values
    # calibrated count: on missed days flag as many as the nowcast expects, i.e. the top mean(p) share (train patients)
    ref = cand & train_mask.values
    expect = float(p[ref].mean())
    tau = float(np.quantile(p[ref], 1 - expect))
    d["nowcast_p"] = np.where(miss, p, np.nan)
    d["rough_proxy"] = (cand & (p >= tau)).astype(int)
    if os.environ.get("C3_PROXY", "1") == "0":
        d["rough_proxy"] = 0
    d["rough"] = ((d.rough_self == 1) | (d.clinical == 1) | (d.rough_proxy == 1)).astype(int)
    rate = lambda k: float(feel_rough[(~miss) & (d.skips_before == k)].mean())
    info = {"nowcast_auc_train_checkin_days": round(float(roc_auc_score(feel_rough[obs], p[obs])), 3),
            "missed_day_expected_rough_share": round(expect, 4), "proxy_threshold": round(tau, 4),
            "rough_rate_after_skips": {str(k): round(rate(k), 3) for k in (0, 1, 2, 3, 5)},
            "unknown_days_share": round(float(unknown.mean()), 3)}
    return info


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
    return f


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


def urgent_metrics(df, score_col, thr):
    """ER/admission events (first in 7 days, day 14+): caught if flagged 2-7 days before. Precision = urgent runs
    followed by an ER/admission within 7 days. AUC/AP over scored days (no ER in the past 7 days)."""
    from sklearn.metrics import average_precision_score
    n, hit, leads, runs, good, months = 0, 0, [], 0, 0, 0.0
    for _, p in df.groupby("patient_id"):
        a = (p[score_col].values >= thr).astype(int)
        er = p.er.values
        months += len(p) / 30.4
        for i in np.where(er == 1)[0]:
            if i < 14 or er[max(0, i - 7):i].any():
                continue
            n += 1
            start = max(0, i - HORIZON)
            w = a[start: i - MIN_LEAD + 1]
            if w.any():
                hit += 1
                leads.append(i - (start + int(np.argmax(w))))
        for i in range(len(a)):
            if a[i] and not a[max(0, i - 3):i].any():
                runs += 1
                good += int(er[i + 1: i + 1 + HORIZON].any())
    q = df[(df.er_recent == 0) & (df.day_in_program >= 14)]
    return {"er_events": n, "er_recall_2to7d": round(hit / max(n, 1), 3),
            "median_lead_days": float(np.median(leads)) if leads else None,
            "flag_precision": round(good / max(runs, 1), 3), "flags_per_patient_month": round(runs / max(months, 1), 2),
            "auc": round(float(roc_auc_score(q.er_ahead, q[score_col])), 3),
            "average_precision": round(float(average_precision_score(q.er_ahead, q[score_col])), 4),
            "base_rate": round(float(q.er_ahead.mean()), 4)}


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
    label_info = None
    if LABEL_VERSION == "v2":
        label_info = label_v2(d, (d.split == "train"))
        episodes(d, d.rough)
        src = np.where(d.clinical == 1, "clinical", np.where(d.rough_self == 1, "self_report", "wearable_proxy"))
        d["onset_source"] = np.where(d.onset == 1, src, "")
    else:
        for c in ("patch", "onset", "in_episode", "target"):
            d[c] = d[f"{c}_v1"]
        d["onset_source"] = ""
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
    rough_day = ("relative to the person: daily feeling 1, or 2+ points below their own median of the last 28 check-ins "
                 "(until 5 check-ins: feeling <= 2); OR on the weekly check-in any of fatigue, nausea, pain, appetite loss, "
                 "diarrhea, trouble sleeping, anxiety, sadness >= 3 or 2+ above their own usual; OR ER visit / admission / "
                 "treatment paused; OR, on a day with no check-in, a same-day wearable nowcast says rough (the run of "
                 "skipped check-ins is an input, so each extra skipped day weighs more); no check-in AND watch off = unknown"
                 ) if LABEL_VERSION == "v2" else \
        "daily feeling <= 2, OR weekly fatigue >= 3, OR ER visit / hospital admission / treatment paused"
    report = {"definition": {
        "label_version": LABEL_VERSION,
        "rough_day": rough_day,
        "rough_patch": "a rough day followed by another within 3 days, or any clinical event; onset = first patch day after 7 quiet days",
        "forecast": f"each evening, P(rough patch onset in the next {HORIZON} days); days already inside a patch are not scored",
        "early_warning": f"an alert counts only if it fires {MIN_LEAD}+ days before onset",
        "inputs": "wearable signals vs personal baseline, wear time, known treatment schedule. No self-reports, no events.",
        "split": "by patient: 60% train, 15% validation (thresholds), 25% test (all numbers below)",
        "alert_budget": f"thresholds put {int(ALERT_RATE*100)}% of quiet validation days on alert, same budget for every method",
    }, "counts": {"patients": int(n), "test_patients": int((pd.Series(split) == 'test').sum()),
                  "onsets_total": int(d.onset.sum()), "label_missing_feeling_share": round(float(d.daily_feeling_1_to_5.isna().mean()), 3)},
        "methods": {}}
    if label_info:
        report["label_v2"] = label_info
        srcs = d.loc[d.onset == 1, "onset_source"].value_counts()
        per = d.groupby("patient_id").onset.sum()
        miss_share = d.groupby("patient_id").daily_feeling_1_to_5.apply(lambda s: s.isna().mean())
        q = pd.qcut(miss_share, 4, labels=["most engaged", "q2", "q3", "least engaged"])
        report["label_v2"].update({
            "onsets_by_source": {k: int(v) for k, v in srcs.items()},
            "onsets_v1_total": int(d.onset_v1.sum()),
            "onsets_per_patient_mean": round(float(per.mean()), 2),
            "onsets_per_patient_by_checkin_engagement": {str(k): round(float(v), 2) for k, v in per.groupby(q).mean().items()}})
    names = {"steps_rule": "Baseline: steps drop", "schedule": "Baseline: treatment schedule only (same learner)",
             "logistic": "Logistic, wearable + schedule (comparison)", "model": "Radar (gradient boosting, wearable + schedule)"}
    for k, nm in names.items():
        report["methods"][k] = {"name": nm, "weeks": week_metrics(test, f"score_{k}", thr[k]["alert"]),
                                "episodes": episode_metrics(test, f"score_{k}", thr[k]["alert"])}
        print(nm, json.dumps(report["methods"][k]))

    # label cross-check: does a model trained on this label catch the onsets everyone agrees on? Compare against a model
    # trained on the v1 label, same learner, same alert budget, on (a) v1 onsets and (b) self-report + clinical onsets.
    if LABEL_VERSION == "v2":
        use1 = (d.in_episode_v1 == 0) & (d.day_in_program >= 14)
        tr1, va1 = [(use1 & (d.split == k)).values for k in ("train", "val")]
        g1 = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED).fit(F[tr1], d.target_v1.values[tr1])
        d["score_model_v1label"] = g1.predict_proba(F)[:, 1]
        thr1 = float(np.quantile(d.loc[va1, "score_model_v1label"], 1 - ALERT_RATE))
        test = d[d.split == "test"]
        core = test.assign(onset=((test.onset == 1) & test.onset_source.isin(["self_report", "clinical"])).astype(int))
        v1on = test.assign(onset=test.onset_v1, in_episode=test.in_episode_v1, target=test.target_v1)
        cc = {}
        for nm_, frame in (("v1_onsets", v1on), ("self_report_and_clinical_onsets", core)):
            cc[nm_] = {k: {kk: vv for kk, vv in episode_metrics(frame, c, th).items()
                           if kk in ("episodes", "episode_recall", "median_lead_days", "alert_precision", "er_recall")}
                       for k, c, th in (("trained_on_v2", "score_model", thr["model"]["alert"]),
                                        ("trained_on_v1", "score_model_v1label", thr1))}
        cc["v1_onsets"]["week_auc"] = {"trained_on_v2": week_metrics(v1on, "score_model", thr["model"]["alert"])["auc"],
                                        "trained_on_v1": week_metrics(v1on, "score_model_v1label", thr1)["auc"]}
        report["label_v2"]["cross_check"] = cc
        print("CROSS-CHECK", json.dumps(cc, indent=1))

    # urgent tier: a separate head for ER visit / hospital admission in the next 7 days, shown as its own flag
    d["er_recent"] = d.groupby("patient_id").er.transform(lambda s: s.rolling(7, min_periods=1).sum()).clip(0, 1)
    use_u = (d.er_recent == 0) & (d.day_in_program >= 14)
    tr_u, va_u = [(use_u & (d.split == k)).values for k in ("train", "val")]
    eu = d.er_ahead.values
    gu = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED).fit(F[tr_u], eu[tr_u])
    gus = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED).fit(F.loc[tr_u, SCHEDULE], eu[tr_u])
    d["score_urgent"] = gu.predict_proba(F)[:, 1]
    d["score_urgent_schedule"] = gus.predict_proba(F[SCHEDULE])[:, 1]
    thr_u = {k: float(np.quantile(d.loc[va_u, c], 1 - URGENT_RATE))
             for k, c in (("urgent", "score_urgent"), ("schedule", "score_urgent_schedule"), ("radar", "score_model"))}
    test = d[d.split == "test"]
    report["urgent"] = {
        "definition": f"P(ER visit or hospital admission in the next {HORIZON} days); urgent when in the top "
                      f"{URGENT_RATE:.0%} of validation days. Separate flag; does not change the rough-patch status.",
        "methods": {k: urgent_metrics(test, c, thr_u[k]) for k, c in
                    (("urgent", "score_urgent"), ("schedule", "score_urgent_schedule"), ("radar", "score_model"))},
        "names": {"urgent": "Urgent head (wearable + schedule)", "schedule": "Urgent head, schedule only",
                  "radar": "Rough-patch Radar used for ER at the same budget"},
        "calibration": calibration(test.assign(target=test.er_ahead, in_episode=test.er_recent), "score_urgent"),
    }
    print("URGENT", json.dumps(report["urgent"]["methods"]))
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
    (OUT / "gbm.pkl").write_bytes(pickle.dumps({"model": gb, "schedule_model": gs, "features": feats, "thresholds": thr["model"],
                                              "urgent_model": gu, "urgent_threshold": thr_u["urgent"]}))
    d.to_parquet(OUT / "scored.parquet")
    F.to_parquet(OUT / "features.parquet")
    print("wrote", OUT / "metrics.json")


if __name__ == "__main__":
    main()
