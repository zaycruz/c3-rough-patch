"""95% CIs (patient bootstrap, held-out test patients) for the urgent ER tier and the diary-note scan.

Usage: python -I analysis/urgent_ci.py      (after analysis/train.py and analysis/notes_scan.py)
Writes: analysis/out/urgent_ci.json

ER outcome, one named baseline: the calendar-only ER model (same learner, treatment calendar only, same 3% urgent
budget set on validation patients). Rules match train.py urgent_metrics: an ER visit / admission (first in 7 days,
day 14+) is caught if flagged 2-7 days before.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from notes_scan import RED_FLAGS, categories  # noqa: E402

OUT = ROOT / "analysis" / "out"
URGENT_RATE, HORIZON, MIN_LEAD, SEED, REPS = 0.03, 7, 2, 7, 1000


def per_patient(t, col):
    """Per patient: [ER events, caught 2-7 d early]."""
    res = []
    for _, p in t.groupby("patient_id"):
        a, er = p[col].values, p.er.values
        n = h = 0
        for i in np.where(er == 1)[0]:
            if i < 14 or er[max(0, i - 7):i].any():
                continue
            n += 1
            h += int(a[max(0, i - HORIZON): i - MIN_LEAD + 1].any())
        res.append([n, h])
    return np.array(res, dtype=float)


def boot(a, b, rng):
    """CI of recall(a) - recall(b), resampling patients."""
    diffs = []
    for _ in range(REPS):
        i = rng.integers(0, len(a), len(a))
        x, y = a[i].sum(0), b[i].sum(0)
        diffs.append(x[1] / max(x[0], 1) - y[1] / max(y[0], 1))
    return [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)]


def main():
    d = pd.read_parquet(OUT / "scored.parquet", columns=["patient_id", "day_in_program", "split", "er", "er_recent",
                                                         "diary_note", "preferred_language", "score_urgent",
                                                         "score_urgent_schedule"])
    art = pickle.loads((OUT / "gbm.pkl").read_bytes())
    va = d[(d.split == "val") & (d.er_recent == 0) & (d.day_in_program >= 14)]
    thr = {k: float(np.quantile(va[f"score_{k}"], 1 - URGENT_RATE)) for k in ("urgent", "urgent_schedule")}
    assert abs(thr["urgent"] - art["urgent_threshold"]) < 1e-12, "urgent threshold does not match train.py"
    d["urgent"] = (d.score_urgent >= thr["urgent"]).astype(int)
    d["calendar"] = (d.score_urgent_schedule >= thr["urgent_schedule"]).astype(int)
    d["note"] = d.diary_note.map(lambda n: bool(categories(n) & set(RED_FLAGS))).astype(int)
    d["urgent_or_note"] = d[["urgent", "note"]].max(axis=1)
    t = d[d.split == "test"]
    rng = np.random.default_rng(SEED)
    P = {k: per_patient(t, k) for k in ("urgent", "calendar", "urgent_or_note")}
    rec = {k: round(float(v[:, 1].sum() / v[:, 0].sum()), 3) for k, v in P.items()}
    out = {"baseline": "Calendar-only ER model (treatment calendar only, same 3% urgent budget)",
           "er_events": int(P["urgent"][:, 0].sum()), "er_caught_2to7d": rec,
           "urgent_minus_calendar_ci95": boot(P["urgent"], P["calendar"], rng),
           "note_scan_gain_ci95": boot(P["urgent_or_note"], P["urgent"], rng),
           "urgent_or_note_minus_calendar_ci95": boot(P["urgent_or_note"], P["calendar"], rng),
           "reps": REPS, "unit": "patients", "by_language": {}}
    for lang, g in t.groupby("preferred_language"):
        q = {k: per_patient(g, k) for k in ("calendar", "urgent", "urgent_or_note")}
        out["by_language"][lang] = {"patients": int(g.patient_id.nunique()), "er_events": int(q["urgent"][:, 0].sum()),
                                    **{k: round(float(v[:, 1].sum() / max(v[:, 0].sum(), 1)), 3) for k, v in q.items()}}
    (OUT / "urgent_ci.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
