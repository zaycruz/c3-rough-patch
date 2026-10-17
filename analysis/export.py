"""Bake a coach's caseload into JSON for the Worker.

Usage: .venv/bin/python -I analysis/export.py   (after train.py)
Picks held-out (test) patients active on AS_OF, scores them as of that evening, explains each score,
and writes src/data/survivors.json and src/data/metrics.json.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "out"
DATA = ROOT / "src" / "data"
AS_OF = pd.Timestamp("2025-01-31")
CASELOAD = 60
WINDOW = 42  # days of history in the charts
SEED = 7
ER_BASE = 0.0119  # share of scored test days followed by an ER visit / admission within 7 days (metrics.json urgent.base_rate)

# wearable signal groups the explanation can name; each maps to the model features it owns
GROUPS = {
    "steps": ["steps_z3", "steps_z7", "active_minutes_z3", "active_minutes_z7"],
    "resting_heart_rate": ["resting_heart_rate_z3", "resting_heart_rate_z7"],
    "hrv_rmssd_ms": ["hrv_rmssd_ms_z3", "hrv_rmssd_ms_z7"],
    "sleep": ["sleep_minutes_z3", "sleep_minutes_z7", "sleep_efficiency_pct_z3", "sleep_efficiency_pct_z7",
              "times_woke_up_z3", "times_woke_up_z7"],
    "skin_temp_change_c": ["skin_temp_change_c_z3", "skin_temp_change_c_z7", "skin_temp_change_c_max3"],
    "wear": ["watch_off_days7", "watch_worn_z7", "minutes_watch_worn_z3", "low_wear_days7"],
    # the person's own check-ins and coaching calls (values up to 3 days ago; skips and missed calls up to today)
    "checkins": ["feel_last", "feel_rel_last", "feel_rel_mean7", "rough_self_14", "sym_max_last", "sym_rel_last",
                 "skip_run", "calls_missed_28"],
}
WEARABLE = ["steps", "resting_heart_rate", "hrv_rmssd_ms", "sleep", "skin_temp_change_c", "wear"]
LABEL = {"steps": "Steps", "resting_heart_rate": "Resting heart rate", "hrv_rmssd_ms": "Heart rate variability",
         "sleep": "Sleep", "skin_temp_change_c": "Skin temperature", "wear": "Watch wear",
         "checkins": "Check-ins"}
NEUTRAL = {"watch_off_days7": 0, "low_wear_days7": 0, "skin_temp_change_c_max3": 0.0}


def _neutral(c, x):
    """'Back to their normal' for a feature: their usual feeling and symptoms, no rough days, no skips, no missed calls."""
    if c == "feel_last":
        return x["feel_last"].iloc[0] - x["feel_rel_last"].iloc[0]
    if c == "sym_max_last":
        return x["sym_max_last"].iloc[0] - max(x["sym_rel_last"].iloc[0], 0)
    return NEUTRAL.get(c, 0.0)


def r(x, n=1):
    return None if x is None or pd.isna(x) else round(float(x), n)


def series(v, n=1):
    return [r(x, n) for x in v]


def drivers(model, row):
    """Counterfactual: set one signal group back to the person's normal, see how much the risk drops."""
    base = model.predict_proba(row)[:, 1][0]
    out = {}
    for g, cols in GROUPS.items():
        cols = [c for c in cols if c in row.columns]
        if not cols:
            continue
        x = row.copy()
        for c in cols:
            x[c] = _neutral(c, row)
        out[g] = base - model.predict_proba(x)[:, 1][0]
    return base, out


def describe(g, h):
    """One evidence line from the last 3 days vs the personal baseline (days t-35..t-8)."""
    last3, base = h.iloc[-3:], h.iloc[-35:-7]
    if g == "steps":
        a, b = last3.steps.mean(), base.steps.median()
        if pd.isna(a) or pd.isna(b) or b == 0:
            return None
        return dict(value=round(a), baseline=round(b), unit="steps/day", change=f"{(a - b) / b:+.0%}", concerning=bool(a < 0.8 * b),
                    text=f"Steps {abs((a - b) / b):.0%} {'below' if a < b else 'above'} their usual ({a:,.0f} vs {b:,.0f} a day, last 3 days)")
    if g == "resting_heart_rate":
        a, b = last3.resting_heart_rate.mean(), base.resting_heart_rate.median()
        if pd.isna(a) or pd.isna(b):
            return None
        return dict(value=r(a), baseline=r(b), unit="bpm", change=f"{a - b:+.1f} bpm", concerning=bool(a - b >= 2),
                    text=f"Resting heart rate {a - b:+.1f} bpm vs their usual ({a:.0f} vs {b:.0f})")
    if g == "hrv_rmssd_ms":
        a, b = last3.hrv_rmssd_ms.mean(), base.hrv_rmssd_ms.median()
        if pd.isna(a) or pd.isna(b) or b == 0:
            return None
        return dict(value=r(a), baseline=r(b), unit="ms", change=f"{(a - b) / b:+.0%}", concerning=bool(a < 0.85 * b),
                    text=f"Heart rate variability {abs((a - b) / b):.0%} {'lower' if a < b else 'higher'} than usual (recovery {'down' if a < b else 'up'})")
    if g == "sleep":
        a, b = last3.sleep_efficiency_pct.mean(), base.sleep_efficiency_pct.median()
        w, wb = last3.times_woke_up.mean(), base.times_woke_up.median()
        m, mb = last3.sleep_minutes.mean(), base.sleep_minutes.median()
        if pd.isna(a) or pd.isna(b):
            return None
        return dict(value=r(a), baseline=r(b), unit="% efficiency", change=f"{a - b:+.0f} pts",
                    concerning=bool(a <= b - 4 or w >= wb + 1.5 or m <= mb - 60),
                    text=f"Sleep efficiency {a:.0f}% vs usual {b:.0f}%, waking {w:.1f}x a night vs {wb:.1f}x, {m / 60:.1f} h asleep vs {mb / 60:.1f} h")
    if g == "skin_temp_change_c":
        a = last3.skin_temp_change_c.max()
        if pd.isna(a):
            return None
        return dict(value=r(a, 2), baseline=0.0, unit="°C vs usual", change=f"{a:+.1f} °C", concerning=bool(a >= 0.4),
                    text=f"Skin temperature up to {a:+.1f} °C from their usual at night")
    if g == "wear":
        off = int(h.iloc[-7:].steps.isna().sum())
        worn, wb = h.iloc[-3:].minutes_watch_worn.mean(), base.minutes_watch_worn.median()
        return dict(value=off, baseline=0, unit="days off of last 7", change=f"{worn / 60:.0f} h/day worn vs {wb / 60:.0f} h",
                    concerning=bool(off >= 2 or (worn == worn and worn < 0.75 * wb)),
                    text=f"Watch off {off} of the last 7 days, worn {worn / 60:.0f} h/day vs usual {wb / 60:.0f} h")
    return None


def describe_checkins(x, h):
    """Evidence line from the person's own check-ins (as the model saw them: ratings up to 3 days ago).
    Also returns kind: 'quiet' when skips or missed calls are the story, 'dip' when ratings or symptoms are."""
    v = {c: x[c].iloc[0] for c in x.columns}
    parts, dip, quiet = [], False, False
    run = int(v["skip_run"])
    if run >= 2:
        k = max(s for s in map(int, SKIP_RATE) if s <= run)
        parts.append(f"skipped the last {run} daily check-ins (people report a rough day {SKIP_RATE[str(k)] / SKIP_RATE['0']:.1f}x "
                     f"as often after {k}+ skips)")
        quiet |= run >= 3
    if v["calls_missed_28"] >= 1:
        parts.append(f"{v['calls_missed_28']:.0f} coaching call(s) missed or moved in 4 weeks")
        quiet = True
    if pd.notna(v["feel_rel_last"]) and v["feel_rel_last"] <= -1:
        parts.append(f"last feeling {v['feel_last']:.0f}/5, below their usual {v['feel_last'] - v['feel_rel_last']:.0f}")
        dip = True
    if v["rough_self_14"] >= 1:
        parts.append(f"{v['rough_self_14']:.0f} rough day(s) reported in the 2 weeks before")
        dip = True
    if pd.notna(v["sym_rel_last"]) and (v["sym_max_last"] >= 3 or v["sym_rel_last"] >= 1):
        parts.append(f"worst weekly symptom {v['sym_max_last']:.0f}/4 ({v['sym_rel_last']:+.0f} vs usual)")
        dip = True
    if not parts:
        return None
    if pd.notna(v["feel_rel_last"]) and not dip:
        parts.append(f"their last rating was their usual {v['feel_last']:.0f}/5")
    text = "; ".join(parts)
    return dict(value=run, baseline=0, unit="check-ins skipped in a row", kind="dip" if dip else "quiet",
                change=f"{run} skipped" if quiet else "below usual", concerning=bool(dip or quiet),
                text=text[0].upper() + text[1:] + " (ratings up to 3 days ago)")


def schedule_context(row):
    plan, doc = row.treatment_plan, row.day_of_cycle
    if row.treatment_phase != "on treatment":
        return f"{row.treatment_phase.capitalize()} ({plan})"
    if pd.notna(doc):
        return f"Day {int(doc)} of cycle {int(row.treatment_cycle)} ({plan})"
    return f"On treatment ({plan})"


def actions(status, top, skin_hot, rhr_up, urgent=False):
    if status == "ok":
        return [{"action": "No change. Keep the regular check-in.", "why": "Check-ins and wearable are near their usual.", "urgency": "routine"}]
    recs = []
    if urgent:
        recs.append({"action": "Call today. Ask how they feel, about fever, fluids and anything new. If anything is off, have them call their care team now.",
                     "why": "Their wearable pattern matches the days before an ER visit or hospital stay. The coach does not diagnose; the care team decides.",
                     "urgency": "today"})
    if skin_hot and rhr_up:
        recs.append({"action": "Call today and ask them to contact their care team about a possible fever or infection.",
                     "why": "Skin temperature and resting heart rate are both up from their usual. The coach should not diagnose; the care team decides.",
                     "urgency": "today"})
    by = {
        "steps": ("Check in this week: ask about energy and what got in the way of moving. Offer a lighter activity goal.",
                  "Movement has dropped well below their usual."),
        "sleep": ("Check in this week about sleep: nights, naps, worries. Share the sleep tips sheet.",
                  "Sleep got shorter or more broken than usual."),
        "resting_heart_rate": ("Call within 2 days. Ask about fatigue, fluids and anything new; suggest they tell their care team if they feel unwell.",
                               "Resting heart rate is rising above their usual."),
        "hrv_rmssd_ms": ("Check in this week and suggest a rest day and a short recovery routine.",
                         "Heart rate variability is down, a sign the body is under strain."),
        "skin_temp_change_c": ("Call within a day and ask whether they have a temperature. If so, point them to their care team.",
                               "Night skin temperature is up from their usual."),
        "schedule": ("Check in before the usual low point after their dose: energy, eating, fluids. Lower this week's goals.",
                     "Their treatment calendar puts them near the low point, when rough patches usually start."),
        "checkins": ("Call this week: their own check-ins have dipped. Ask what changed and what would help this week.",
                     "Their own ratings or weekly symptoms are worse than their usual."),
        "checkins_quiet": ("Send a short, no-pressure message asking how the week is going; offer a 2-minute call instead of the form.",
                           "They have gone quiet: skipped check-ins or missed calls come before rough days more often than not checking in."),
        "wear": ("Send a friendly message: is the watch OK, and how are they doing? A quiet watch often means a hard week.",
                 "The watch has been off more than usual."),
    }
    if top in by:
        a, w = by[top]
        recs.append({"action": a, "why": w, "urgency": "this week" if status == "watch" else "within 2 days"})
    recs.append({"action": "Move the next coaching call earlier and plan around the expected low point.",
                 "why": "The forecast covers the next 7 days.", "urgency": "this week"})
    return recs


def main():
    global SKIP_RATE, NOWCAST_BASE
    lv2 = json.loads((OUT / "metrics.json").read_text())["label_v2"]
    SKIP_RATE, NOWCAST_BASE = lv2["rough_rate_after_skips"], lv2["missed_day_expected_rough_share"]
    art = pickle.loads((OUT / "gbm.pkl").read_bytes())
    gb, gs, feats, thr = art["model"], art["schedule_model"], art["features"], art["thresholds"]
    gu, thr_u = art["urgent_model"], art["urgent_threshold"]
    ufeats = art.get("urgent_features", feats)
    sys.path.insert(0, str(ROOT / "analysis"))
    from train import SCHEDULE
    d = pd.read_parquet(OUT / "scored.parquet")
    F = pd.read_parquet(OUT / "features.parquet")
    today = d[(d.date == AS_OF) & (d.split == "test") & (d.day_in_program >= 28)]
    pick = today.sample(min(CASELOAD, len(today)), random_state=SEED)
    survivors, details = [], {}
    for idx, row in pick.iterrows():
        pid = row.patient_id
        hist = d[(d.patient_id == pid) & (d.date <= AS_OF)].tail(WINDOW + 35)
        x = F.loc[[idx], feats]
        score, contrib = drivers(gb, x)
        sched = float(gs.predict_proba(F.loc[[idx], SCHEDULE])[:, 1][0])
        status = "alert" if score >= thr["alert"] else "watch" if score >= thr["watch"] else "ok"
        urgent_risk = float(gu.predict_proba(F.loc[[idx], ufeats])[:, 1][0])
        urgent = urgent_risk >= thr_u
        if urgent:
            status = "alert"  # an ER-level risk is always a rough patch soon
        ranked = sorted(contrib.items(), key=lambda kv: -kv[1])
        # a wearable signal is a driver only if it moved the risk AND moved in a worrying direction
        evidence, ck_kind = [], None
        for g, c in ranked:
            line = describe_checkins(x, hist) if g == "checkins" else describe(g, hist)
            if line and g == "checkins":
                ck_kind = line.pop("kind")
            if line and c >= 0.01 and line.pop("concerning"):
                evidence.append({"signal": g, "label": LABEL[g], "riskShare": round(float(c), 3), **line})
            if len(evidence) == 3:
                break
        run = int(x["skip_run"].iloc[0]) if "skip_run" in x.columns else 0
        evidence.append({"signal": "schedule", "label": "Treatment calendar", "riskShare": round(sched, 3),
                         "text": f"{schedule_context(row)}. The calendar alone predicts {sched:.0%} risk of a rough patch this week."})
        last3 = hist.iloc[-3:]
        skin_hot = bool((last3.skin_temp_change_c > 0.5).any())
        rhr_up = bool(last3.resting_heart_rate.mean() - hist.iloc[-35:-7].resting_heart_rate.median() > 3)
        wev = [e for e in evidence if e["signal"] != "schedule"]
        top = wev[0]["signal"] if wev and score - sched > 0.02 else "schedule"
        ck = float(contrib.get("checkins", 0.0))
        wear_part = score - sched - ck
        if urgent:
            headline = f"Urgent: ER or hospital risk {urgent_risk:.0%} in the next 7 days, about {urgent_risk / ER_BASE:.0f}x usual"
        elif status == "ok":
            headline = "Steady. Check-ins and wearable near their usual."
        elif top == "schedule" and score - sched > 0.03:
            headline = f"Rough patch risk {score:.0%} in the next 7 days, from several small changes"
        elif top == "schedule":
            headline = f"Rough patch risk {score:.0%} in the next 7 days, mostly from the treatment calendar"
        else:
            what = ("going quiet (skipped check-ins)" if top == "checkins" and ck_kind == "quiet"
                    else LABEL.get(top, "the treatment calendar").lower())
            headline = f"Rough patch risk {score:.0%} in the next 7 days, driven by {what}"
        summary = ((f"Urgent: risk of an ER visit or hospital admission in the next 7 days is {urgent_risk:.0%} "
                    f"(urgent line {thr_u:.0%}, typical day {ER_BASE:.1%}). ") if urgent else "") + (f"Risk of a rough patch in the next 7 days: {score:.0%} (alert line {thr['alert']:.0%}). "
                   f"The treatment calendar alone gives {sched:.0%}; their check-ins move it {int(round(ck * 100)):+d} points and "
                   f"wearable signals {int(round(wear_part * 100)):+d}. "
                   + ("Biggest driver: " + wev[0]["text"] + "." if top != "schedule"
                      else "Several small changes add up; no single signal is far out of line."
                      if score - sched > 0.03
                      else "Also worth noting: " + wev[0]["text"] + "." if wev
                      else "Nothing is out of line; the risk comes from where they are in treatment."))
        h = hist.tail(WINDOW)
        hf = F.loc[h.index, feats]
        risk = gb.predict_proba(hf)[:, 1]
        sid = f"c3-{pid}"
        nxt = d[(d.patient_id == pid) & (d.date > AS_OF)].head(14)
        onset_in = nxt.index[nxt.onset == 1]
        er_in = nxt.index[nxt.er == 1]
        name = f"{pid} · {int(row.age)}{row.sex[0].upper()} · {row.cancer_type}"
        survivors.append({"survivorId": sid, "displayName": name, "status": status, "headline": headline,
                          "updatedAt": AS_OF.strftime("%Y-%m-%dT20:00:00Z"), "urgent": bool(urgent), "risk": round(score, 3)})
        details[sid] = {
            "survivorId": sid, "displayName": name, "status": status, "headline": headline, "summary": summary,
            "urgent": bool(urgent), "urgentRisk": round(urgent_risk, 3),
            "risk": round(score, 3), "scheduleRisk": round(sched, 3),
            "thresholds": {**{k: round(v, 3) for k, v in thr.items()}, "urgent": round(thr_u, 3)},
            "profile": {"age": int(row.age), "sex": row.sex, "cancerType": row.cancer_type, "stage": row.stage,
                        "treatmentPlan": row.treatment_plan, "device": row.device, "language": row.preferred_language,
                        "livesAlone": row.lives_alone, "context": schedule_context(row)},
            "evidence": evidence,
            "recommendations": actions(status, "checkins_quiet" if top == "checkins" and ck_kind == "quiet" else top,
                                       skin_hot, rhr_up, urgent) + ([{
                "action": "Send a short, no-pressure message asking how the week is going; offer a 2-minute call instead of the form.",
                "why": f"{run} daily check-ins skipped in a row; rough days are more common after a run of skips.",
                "urgency": "this week"}] if run >= 3 and top != "checkins" and status != "ok" else []),
            "charts": {
                "dates": [t.strftime("%Y-%m-%d") for t in h.date],
                "risk": series(risk, 3),
                "urgentRisk": series(gu.predict_proba(F.loc[h.index, ufeats])[:, 1], 3),
                "steps": series(h.steps, 0),
                "restingHeartRate": series(h.resting_heart_rate),
                "hrv": series(h.hrv_rmssd_ms),
                "sleepHours": series(h.sleep_minutes / 60, 2),
                "skinTempChange": series(h.skin_temp_change_c, 2),
                "watchWornHours": series(h.minutes_watch_worn / 60, 1),
                "doseDays": [int(v) for v in h.treatment_today],
                "selfReportedFeeling": series(h.daily_feeling_1_to_5, 0),
            },
            "demo": {"note": "Hidden from the coach view: what actually happened in the 14 days after the forecast.",
                     "roughPatchStartsInDays": int(nxt.index.get_loc(onset_in[0]) + 1) if len(onset_in) else None,
                     "erOrAdmissionInDays": int(nxt.index.get_loc(er_in[0]) + 1) if len(er_in) else None,
                     "events": [f"{t:%Y-%m-%d}: {e}" for t, e in zip(nxt.date, nxt.events) if isinstance(e, str)]},
        }
    order = {"alert": 0, "watch": 1, "ok": 2}
    survivors.sort(key=lambda s: (not s["urgent"], order[s["status"]], -s["risk"]))
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "survivors.json").write_text(json.dumps({"asOf": AS_OF.strftime("%Y-%m-%d"), "roster": survivors, "details": details}))
    m = json.loads((OUT / "metrics.json").read_text())
    rc = OUT / "real_check.json"
    if rc.exists():
        m["realDataCheck"] = json.loads(rc.read_text())
    (DATA / "metrics.json").write_text(json.dumps(m))
    print(pd.Series([s["status"] for s in survivors]).value_counts().to_dict())
    hits = sum(1 for s in survivors if s["status"] != "ok" and details[s["survivorId"]]["demo"]["roughPatchStartsInDays"])
    print("flagged with a patch in 14d:", hits, "/", sum(s["status"] != "ok" for s in survivors))
    print("size", (DATA / "survivors.json").stat().st_size)


if __name__ == "__main__":
    main()
