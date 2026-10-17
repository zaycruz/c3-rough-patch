"""Model-free red-flag escalation: same-day rules a coach can read, from the check-in and the diary note, in English,
Spanish and Haitian Creole. No model, no score: the same input always gives the same call on every platform.

Usage: python -I analysis/escalation.py      (after analysis/train.py and analysis/notes_scan.py)
Writes: analysis/out/escalation.json

Three same-day triggers, each a "call today" for the coach:
  1. note red flag: the diary-note word list in analysis/notes_scan.py (fever, can't keep fluids, chest or breathing,
     bleeding, a fall, distress, called the care team).
  2. passive ideation: a death-wish or "better off without me" phrase in the note (PASSIVE below). This is a
     safety-of-life trigger: the coach calls today and follows the program's suicide-risk protocol. The synthetic data
     contains no such notes, so there is no outcome to validate it against; it is tested only on the cases below.
  3. check-in symptom rule: one of the candidate rules below, picked on validation patients, scored once on test.
Mood (weekly sadness or anxiety at 4 of 4) is counted and served as a call reason, but it is not validated against
ER visits, since an ER visit is the wrong outcome for it.

Failure modes, written before the rules (the script stops if any case fails):
  F1 passive ideation missed: different phrasings in English, Spanish and Creole (CASES, want True).
  F2 idioms raise a false alarm: "dying to see", "me muero de ganas", "mwen mouri ri", "this heat is killing me"
     (CASES, want False).
  F3 negation over-calls: "I don't want to die, I want to fight" fires. Accepted and stated: a call is cheap, a miss is not.
  F4 a missing check-in fires the rule (NaN must never count as a 4 or a 1).
  F5 the rule reads another day's answer: it reads only that day's row.
  F6 -0.0 in the weekly items is treated differently from 0.
  F7 an "already in care" note (ER last night) fires as a warning: it must not.
  F8 the rule's workload is unbounded: report flag days per patient-month and calls per coach per week.
  F9 the rule flags one language group far more often: report flag rate by language.

Check-in rule candidates (fixed before running): C1 daily feeling 1 of 5; C2 nausea, pain, appetite loss or diarrhea
at 4 of 4; C3 C1 or C2; C4 two or more of the eight weekly items at 3 or more. Selection rule (fixed before running):
on validation patients, among candidates with at most 0.5 flag days per patient-month, the one with the highest share of
flag days followed by an ER visit or admission within 7 days; ties go to the simpler rule (lower number).

Caseload per coach is a parameter (CASELOAD); the sponsor brief gives no number. 60 is the demo caseload.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from notes_scan import HORIZON, MIN_LEAD, RED_FLAGS, categories, er_window_hits  # noqa: E402
from urgent_ci import boot, per_patient  # noqa: E402

import re  # noqa: E402

OUT = ROOT / "analysis" / "out"
CASELOAD = 60
WEEKS_PER_MONTH = 30.4 / 7
MAX_FLAG_RATE = 0.5
SEED = 7

PASSIVE = {
    "en": [r"wish i (?:would ?n[o']?t|wouldn'?t|didn'?t) wake up", r"(?:don'?t|do not) want to (?:live|be here|wake up)",
           r"better off without me", r"(?:tired|sick) of (?:living|being alive)", r"wish i (?:was|were) dead",
           r"want to die", r"no reason to (?:live|go on)", r"end it all", r"can'?t go on"],
    "es": [r"no quiero (?:vivir|seguir viviendo|despertar)", r"ojal[aá] no (?:despertara|despierte|despertar)",
           r"(?:estar[ií]an|estar[aá]n) mejor sin m[ií]", r"cansad[ao] de vivir", r"quiero morir(?:me)?",
           r"mejor (?:estar|estaría) muert[ao]", r"no vale la pena vivir", r"ya no puedo m[aá]s"],
    "ht": [r"pa vle viv", r"vle mouri", r"(?:ta pito|pito) mouri", r"bouke viv", r"(?:yo|fanmi m) (?:ta )?pi byen san mwen",
           r"pa gen rezon pou m viv", r"m ta renmen pa leve"],
}
IDIOMS = [r"dying to\b", r"me muero de (?:ganas|risa|hambre|calor|sueño)", r"mouri ri", r"killing me"]
_PASSIVE = re.compile("|".join(p for ps in PASSIVE.values() for p in ps), re.I)
_IDIOM = re.compile("|".join(IDIOMS), re.I)

CASES = [
    # F1: passive ideation, each language, several phrasings
    ("Some nights I wish I wouldn't wake up", True),
    ("Honestly they'd be better off without me", True),
    ("So tired of living like this", True),
    ("I don't want to be here anymore", True),
    ("Can't go on like this", True),
    ("No quiero seguir viviendo así", True),
    ("Ojalá no despertara mañana", True),
    ("Estarían mejor sin mí", True),
    ("Estoy cansada de vivir", True),
    ("Ya no puedo más", True),
    ("Mwen pa vle viv ankò", True),
    ("M ta pito mouri", True),
    ("Mwen bouke viv", True),
    ("Fanmi m ta pi byen san mwen", True),
    # F3: negation over-calls, accepted
    ("I don't want to die, I want to fight this", True),
    # F2: idioms and ordinary complaints must not fire
    ("Dying to see my grandkids this weekend", False),
    ("Me muero de ganas de ir a la playa", False),
    ("Me muero de calor", False),
    ("Mwen mouri ri ak pitit mwen", False),
    ("This heat is killing me", False),
    ("Tired today, slept badly", False),
    ("Living room is finally clean", False),
    ("Mwen fatige anpil jodi a.", False),
    ("Worried about my scan next week.", False),
    # F7: already in care
    ("ER last night. Getting fluids.", False),
]
WEEKLY = ["weekly_fatigue_0_to_4", "weekly_nausea_0_to_4", "weekly_pain_0_to_4", "weekly_appetite_loss_0_to_4",
          "weekly_diarrhea_0_to_4", "weekly_trouble_sleeping_0_to_4", "weekly_anxiety_0_to_4", "weekly_sadness_0_to_4"]
PHYSICAL = ["weekly_nausea_0_to_4", "weekly_pain_0_to_4", "weekly_appetite_loss_0_to_4", "weekly_diarrhea_0_to_4"]
MOOD = ["weekly_anxiety_0_to_4", "weekly_sadness_0_to_4"]

# F4/F5/F6: one row = one person-day; NaN = not answered that day
RULE_CASES = [
    ({"daily_feeling_1_to_5": np.nan, **{c: np.nan for c in WEEKLY}}, {"C1": 0, "C2": 0, "C3": 0, "C4": 0, "mood": 0}),
    ({"daily_feeling_1_to_5": 1.0, **{c: np.nan for c in WEEKLY}}, {"C1": 1, "C2": 0, "C3": 1, "C4": 0, "mood": 0}),
    ({"daily_feeling_1_to_5": 2.0, **{c: -0.0 for c in WEEKLY}}, {"C1": 0, "C2": 0, "C3": 0, "C4": 0, "mood": 0}),
    ({"daily_feeling_1_to_5": np.nan, **{c: 0.0 for c in WEEKLY}, "weekly_pain_0_to_4": 4.0},
     {"C1": 0, "C2": 1, "C3": 1, "C4": 0, "mood": 0}),
    ({"daily_feeling_1_to_5": np.nan, **{c: 0.0 for c in WEEKLY}, "weekly_fatigue_0_to_4": 4.0},
     {"C1": 0, "C2": 0, "C3": 0, "C4": 0, "mood": 0}),
    ({"daily_feeling_1_to_5": 3.0, **{c: 1.0 for c in WEEKLY}, "weekly_fatigue_0_to_4": 3.0, "weekly_sadness_0_to_4": 4.0},
     {"C1": 0, "C2": 0, "C3": 0, "C4": 1, "mood": 1}),
]


def passive_ideation(note):
    return isinstance(note, str) and bool(_PASSIVE.search(_IDIOM.sub(" ", note)))


def rules(d):
    """Candidate check-in rules on each row's own answers (NaN compares False)."""
    w = d[WEEKLY].astype(float)
    r = pd.DataFrame(index=d.index)
    r["C1"] = (d.daily_feeling_1_to_5 == 1).astype(int)
    r["C2"] = (d[PHYSICAL] >= 4).any(axis=1).astype(int)
    r["C3"] = r[["C1", "C2"]].max(axis=1)
    r["C4"] = ((w >= 3).sum(axis=1) >= 2).astype(int)
    r["mood"] = (d[MOOD] >= 4).any(axis=1).astype(int)
    return r


def self_test():
    bad = [(n, want) for n, want in CASES if passive_ideation(n) != want]
    bad += [("note red flag fired on an already-in-care note", None)] if categories("ER last night. Getting fluids.") & set(RED_FLAGS) else []
    got = rules(pd.DataFrame([row for row, _ in RULE_CASES]))
    for i, (_, want) in enumerate(RULE_CASES):
        if {k: int(got.iloc[i][k]) for k in want} != want:
            bad.append((f"rule case {i}", want))
    for b in bad:
        print("CASE FAILED:", b)
    return {"cases": len(CASES) + len(RULE_CASES) + 1, "failed": len(bad)}


def evaluate(t, col):
    """Flag days, share followed by ER within 7 d, ER events caught 2-7 d and 1-7 d early (rules of notes_scan.py)."""
    q = t[(t.er_recent == 0) & (t.day_in_program >= 14)]
    f = q[q[col] == 1]
    n27 = h27 = n17 = h17 = 0
    for _, p in t.groupby("patient_id"):
        a, er = p[col].values, p.er.values
        e, h = er_window_hits(a, er, MIN_LEAD, HORIZON); n27 += e; h27 += h
        e, h = er_window_hits(a, er, 1, HORIZON); n17 += e; h17 += h
    rate = len(t[t[col] == 1]) / (len(t) / 30.4)
    prec = float(f.er_ahead.mean()) if len(f) else 0.0
    base = float(q.er_ahead.mean())
    return {"flag_days": int((t[col] == 1).sum()), "flag_days_per_patient_month": round(rate, 3),
            "calls_per_coach_week": round(rate * CASELOAD / WEEKS_PER_MONTH, 1),
            "er_within_7d_when_flagged": round(prec, 3), "times_base_rate": round(prec / base, 1) if base else None,
            "calls_per_er_or_admission_followed": round(1 / prec, 1) if prec else None,
            "er_events": n27, "er_caught_2to7d": round(h27 / max(n27, 1), 3), "er_caught_1to7d": round(h17 / max(n17, 1), 3)}


def main():
    st = self_test()
    if st["failed"]:
        sys.exit(f"{st['failed']} of {st['cases']} cases failed")
    cols = ["patient_id", "day_in_program", "split", "er", "er_ahead", "er_recent", "diary_note", "preferred_language",
            "score_urgent", "daily_feeling_1_to_5", *WEEKLY]
    d = pd.read_parquet(OUT / "scored.parquet", columns=cols)
    d = pd.concat([d, rules(d)], axis=1)
    d["note"] = d.diary_note.map(lambda n: bool(categories(n) & set(RED_FLAGS))).astype(int)
    d["ideation"] = d.diary_note.map(passive_ideation).astype(int)
    out = {"what": "Model-free same-day escalation: note red flag, passive ideation, check-in symptom rule. "
                   "No model; identical on every platform.",
           "self_test": st, "caseload_per_coach": CASELOAD, "caseload_note": "parameter; the sponsor brief gives no caseload",
           "candidates": {"C1": "daily feeling 1 of 5", "C2": "nausea, pain, appetite loss or diarrhea at 4 of 4",
                          "C3": "C1 or C2", "C4": "two or more weekly items at 3 or more"},
           "selection_rule": f"val: max share of flag days followed by ER within 7 d, among rules with <= {MAX_FLAG_RATE} "
                             "flag days per patient-month; ties to the lower number",
           "val": {}, "test": {}}
    va = d[d.split == "val"]
    for c in ("C1", "C2", "C3", "C4"):
        out["val"][c] = evaluate(va, c)
    ok = [c for c in ("C1", "C2", "C3", "C4") if out["val"][c]["flag_days_per_patient_month"] <= MAX_FLAG_RATE]
    pick = max(ok, key=lambda c: (out["val"][c]["er_within_7d_when_flagged"], -int(c[1]))) if ok else \
        min(("C1", "C2", "C3", "C4"), key=lambda c: out["val"][c]["flag_days_per_patient_month"])
    out["picked_rule"] = pick
    d["checkin"] = d[pick]
    d["escalation"] = d[["note", "ideation", "checkin"]].max(axis=1)
    thr_u = pickle.loads((OUT / "gbm.pkl").read_bytes())["urgent_threshold"]
    d["urgent"] = (d.score_urgent >= thr_u).astype(int)
    d["urgent_or_escalation"] = d[["urgent", "escalation"]].max(axis=1)
    t = d[d.split == "test"]
    for c in ("note", "ideation", "checkin", "mood", "escalation", "urgent", "urgent_or_escalation"):
        out["test"][c] = evaluate(t, c)
    rng = np.random.default_rng(SEED)
    P = {k: per_patient(t, k) for k in ("urgent", "urgent_or_escalation")}
    out["test"]["escalation_gain_over_urgent_ci95"] = boot(P["urgent_or_escalation"], P["urgent"], rng)
    out["test"]["by_language"] = {}
    for lang, g in t.groupby("preferred_language"):
        months = len(g) / 30.4
        out["test"]["by_language"][lang] = {
            "patients": int(g.patient_id.nunique()),
            **{f"{k}_flag_days_per_patient_month": round(int(g[k].sum()) / months, 3)
               for k in ("note", "ideation", "checkin", "mood", "escalation")},
            **{f"{k}_er_caught_2to7d": round(float((v := per_patient(g, k))[:, 1].sum() / max(v[:, 0].sum(), 1)), 3)
               for k in ("escalation", "urgent", "urgent_or_escalation")},
            "er_events": int(per_patient(g, "urgent")[:, 0].sum())}
    out["test"]["ideation_notes_in_data"] = int(d.ideation.sum())
    (OUT / "escalation.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
