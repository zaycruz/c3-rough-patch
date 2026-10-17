"""Diary-note red-flag scan (English, Spanish, Haitian Creole): a same-day human-review flag, not a model input.

Usage: python -I analysis/notes_scan.py            (after analysis/train.py; reads analysis/out/scored.parquet)
Writes: analysis/out/notes_scan.json

How it works: a fixed word list per red-flag category and language, matched against the day's diary note. A hit asks
the coach to read the note and call today; it does not change the rough-patch or urgent scores. Notes that report an
ER visit or hospital stay that already happened are a separate category ('already_in_care'): they describe the event,
so they are not counted as warnings.

The word list was written from the note templates (all patients) before looking at outcomes; nothing is tuned on
outcomes. CASES below are the failure modes, written first; the script stops if any of them fails.
"""
import json
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "out"
HORIZON, MIN_LEAD = 7, 2

# category -> {language: [regex, ...]}; matched case-insensitively against the whole note
LEXICON = {
    "fever_infection": {
        "en": [r"\bfever", r"\bchills\b", r"took my temp", r"\btemp(erature)? (is |was |of )?\d", r"hot and shaky",
               r"like the flu", r"nurse line.*goes over"],
        "es": [r"fiebre", r"escalofr[ií]o", r"temperatura", r"como (una )?gripe", r"enfermera.*pasa de"],
        "ht": [r"lafy[eè]v", r"fris[oò]n", r"tanperati", r"tankou grip"],
    },
    "cant_keep_fluids": {
        "en": [r"(can'?t|cannot|couldn'?t|could not) keep (any )?(water|fluids|food|anything) down", r"threw up",
               r"\bvomit", r"peeing (very )?little", r"mouth so dry"],
        "es": [r"vomit", r"no (puedo|pude) (retener|tomar) (nada|agua|l[ií]quidos)", r"orino (muy )?poco"],
        "ht": [r"\bvomi", r"pa ka kenbe (dlo|manje|anyen)", r"pipi (yon ti kras|piti)"],
    },
    "called_care_team": {
        "en": [r"called the (nurse|doctor|oncologist|clinic)", r"said (to )?come in"],
        "es": [r"llam[eé] a la (enfermera|doctora?|cl[ií]nica)", r"dijo que (vaya|venga)"],
        "ht": [r"rele (enfimy[eè]|dokt[eè]|klinik)"],
    },
    "breathing_chest": {
        "en": [r"short(ness)? of breath", r"can'?t (catch my )?breath", r"chest (pain|hurts|tight)"],
        "es": [r"falta de aire", r"no puedo respirar", r"dolor (en el|de) pecho"],
        "ht": [r"souf (mwen )?kout", r"pa ka respire", r"(doul[eè]|f[eè] mal) nan (pwatrin|lestomak)"],
    },
    "bleeding": {
        "en": [r"\bbleed", r"blood in (my )?(stool|urine|pee|vomit)", r"coughing (up )?blood"],
        "es": [r"sangr", r"sangre en"],
        "ht": [r"senyen", r"san nan"],
    },
    "fall": {
        "en": [r"\bfell\b", r"\bhad a fall\b", r"\bfall(en)? (down|in the)"],
        "es": [r"\bme ca[ií]", r"\bca[ií] (en|al)\b", r"una ca[ií]da"],
        "ht": [r"\btonbe\b"],
    },
    "distress": {
        "en": [r"hopeless", r"give up", r"want this week to end", r"worst day", r"want to die", r"no point",
               r"didn'?t want to talk to anyone"],
        "es": [r"sin esperanza", r"rendirme", r"me siento fatal", r"el peor d[ií]a", r"quiero morir",
               r"no quise hablar con nadie"],
        "ht": [r"dekouraje", r"pa vle viv", r"vle mouri", r"m bouke ak lavi"],
    },
    "already_in_care": {  # reports of an ER visit / hospital stay that already happened: not a warning
        "en": [r"\bER\b", r"emergency room", r"hospital", r"getting fluids"],
        "es": [r"emergencias", r"hospital", r"suero"],
        "ht": [r"lopital", r"ijans"],
    },
}
RED_FLAGS = [c for c in LEXICON if c != "already_in_care"]
_RX = {c: re.compile("|".join(p for ps in langs.values() for p in ps), re.I) for c, langs in LEXICON.items()}

# Failure modes, written before the word list. (note, expected categories). Any mismatch stops the script.
CASES = [
    # each red flag fires in each language
    ("Chills tonight, took my temp 38.4", {"fever_infection"}),
    ("Escalofríos esta noche, tengo 38.6 de fiebre", {"fever_infection"}),
    ("Mwen gen lafyèv ak frison", {"fever_infection"}),
    ("Feel hot and shaky", {"fever_infection"}),
    ("Threw up twice, couldn't keep water down", {"cant_keep_fluids"}),
    ("Vomité dos veces.", {"cant_keep_fluids"}),
    ("Mwen vomi, mwen pa ka kenbe dlo", {"cant_keep_fluids"}),
    ("Mouth so dry, peeing very little", {"cant_keep_fluids"}),
    ("Called the nurse line, they said come in if it goes over 38.0", {"called_care_team", "fever_infection"}),
    ("Llamé a la enfermera, dijo que vaya si pasa de 38", {"called_care_team", "fever_infection"}),
    ("Chest pain since this morning, short of breath", {"breathing_chest"}),
    ("Dolor de pecho y falta de aire", {"breathing_chest"}),
    ("Mwen gen doulè nan pwatrin, souf mwen kout", {"breathing_chest"}),
    ("I fell in the bathroom", {"fall"}),
    ("Me caí en la cocina", {"fall"}),
    ("Mwen tonbe nan twalèt la", {"fall"}),
    ("Some bleeding from my gums", {"bleeding"}),
    ("Feel awful. Just want this week to end", {"distress"}),
    ("Me siento fatal. Quiero que pase esta semana", {"distress"}),
    ("Mwen dekouraje, mwen pa vle viv konsa", {"distress"}),
    # event reports are their own category, not a warning
    ("ER last night. Getting fluids.", {"already_in_care"}),
    ("Fui a emergencias anoche, me pusieron suero.", {"already_in_care"}),
    ("In the hospital, they're giving me antibiotics", {"already_in_care"}),
    # false alarms the list must not raise: heat, hot flashes, walks, ordinary tiredness, mild symptoms
    ("Walked on the beach early before it got hot", set()),
    ("Too hot to walk outside today.", set()),
    ("Hot flashes all night", set()),
    ("Mucho calor para caminar afuera.", set()),
    ("Feeling strong today", set()),
    ("Mwen santi m pi byen.", set()),
    ("Mwen fatige anpil jodi a.", set()),
    ("Nausea all morning, ate crackers", set()),
    ("Worried about my scan next week.", set()),
    ("Fall is my favorite season", set()),
    ("Treatment day, my wife drove me", set()),
    ("Infusion day. Long wait but the nurses were great.", set()),
]


def categories(note):
    if not isinstance(note, str) or not note.strip():
        return set()
    return {c for c, rx in _RX.items() if rx.search(note)}


def self_test():
    bad = [(n, sorted(want), sorted(categories(n))) for n, want in CASES if categories(n) != want]
    for n, want, got in bad:
        print(f"CASE FAILED: {n!r}: want {want}, got {got}")
    return {"cases": len(CASES), "failed": len(bad)}


def er_window_hits(flags, er, lo, hi):
    """ER/admissions (first in 7 days, day 14+) with a flag lo..hi days before. Returns (events, caught)."""
    n = hit = 0
    for i in np.where(er == 1)[0]:
        if i < 14 or er[max(0, i - 7):i].any():
            continue
        n += 1
        hit += int(flags[max(0, i - hi): i - lo + 1].any())
    return n, hit


def main():
    st = self_test()
    if st["failed"]:
        sys.exit(f"{st['failed']} of {st['cases']} cases failed")
    cols = ["patient_id", "day_in_program", "diary_note", "preferred_language", "split", "er", "er_ahead", "er_recent",
            "score_urgent"]
    d = pd.read_parquet(OUT / "scored.parquet", columns=cols)
    thr_u = pickle.loads((OUT / "gbm.pkl").read_bytes())["urgent_threshold"]
    cats = d.diary_note.map(categories)
    for c in LEXICON:
        d[f"n_{c}"] = cats.map(lambda s, c=c: c in s).astype(int)
    d["note_flag"] = d[[f"n_{c}" for c in RED_FLAGS]].max(axis=1)
    d["urgent_flag"] = (d.score_urgent >= thr_u).astype(int)
    d["either"] = d[["note_flag", "urgent_flag"]].max(axis=1)

    # coverage by the person's language (all patients): how many notes, how many raise a flag
    has = d.diary_note.notna()
    cov = {}
    for lang, g in d[has].groupby("preferred_language"):
        cov[lang] = {"notes": int(len(g)), "red_flag_notes": int(g.note_flag.sum()),
                     "red_flag_share": round(float(g.note_flag.mean()), 4),
                     "already_in_care_notes": int(g.n_already_in_care.sum())}

    out = {"what": "Same-day human-review flag from the diary note (English, Spanish, Haitian Creole word list). "
                   "Not a model input; does not change the rough-patch or urgent scores.",
           "self_test": st, "categories": {c: {k: len(v) for k, v in LEXICON[c].items()} for c in LEXICON},
           "coverage_by_language": cov, "evaluation": {}}
    for split in ("val", "test"):
        t = d[d.split == split]
        q = t[(t.er_recent == 0) & (t.day_in_program >= 14)]
        base = float(q.er_ahead.mean())
        ev = {"patients": int(t.patient_id.nunique()), "scored_days": int(len(q)), "er_base_rate_7d": round(base, 4),
              "by_category": {}}
        for c in RED_FLAGS + ["already_in_care"]:
            f = q[q[f"n_{c}"] == 1]
            ev["by_category"][c] = {"days": int(len(f)),
                                    "er_within_7d": round(float(f.er_ahead.mean()), 3) if len(f) else None}
        months = len(t) / 30.4
        res = {}
        for name, col in (("note_scan", "note_flag"), ("urgent_tier", "urgent_flag"), ("urgent_or_note", "either")):
            f = q[q[col] == 1]
            n27 = h27 = n17 = h17 = 0
            for _, p in t.groupby("patient_id"):
                a = p[col].values
                e, h = er_window_hits(a, p.er.values, MIN_LEAD, HORIZON); n27 += e; h27 += h
                e, h = er_window_hits(a, p.er.values, 1, HORIZON); n17 += e; h17 += h
            prec = float(f.er_ahead.mean()) if len(f) else 0.0
            res[name] = {"flag_days": int(len(f)), "flag_days_per_patient_month": round(len(f) / months, 2),
                         "er_within_7d_when_flagged": round(prec, 3), "times_base_rate": round(prec / base, 1) if base else None,
                         "er_events": n27, "er_caught_2to7d": round(h27 / max(n27, 1), 3),
                         "er_caught_1to7d": round(h17 / max(n17, 1), 3)}
        ev["flags"] = res
        out["evaluation"][split] = ev
    # worked examples from held-out patients: the first red-flag note of each category, per language of the note text
    t = d[(d.split == "test") & (d.note_flag == 1) & (d.er_recent == 0)].copy()
    t["note_language"] = np.where(t.diary_note.str.contains(r"\b(?:Mwen|jodi|anpil|santi)\b"), "Haitian Creole",
                                  np.where(t.diary_note.str.contains(r"[áéíóúñ¿¡]|\b(?:Me|Tengo|Hoy|Fui)\b"), "Spanish", "English"))
    ex = []
    for (lang, cat), g in t.assign(cat=t.diary_note.map(lambda n: sorted(categories(n) & set(RED_FLAGS))[0])).groupby(
            ["note_language", "cat"]):
        r = g.sort_values(["patient_id", "day_in_program"]).iloc[0]
        ex.append({"noteLanguage": lang, "category": cat, "note": r.diary_note, "patientId": r.patient_id,
                   "erOrAdmissionWithin7Days": bool(r.er_ahead)})
    out["examples_test"] = ex
    (OUT / "notes_scan.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
