"""Wearable signals before an ER visit or admission (README: "resting heart rate climbs about 3 bpm and steps fall
about 850 a day from roughly 8 days before").

For each first ER visit / admission (none in the 30 days before), average resting heart rate and steps on each of the
14 days before it, minus the person's own baseline (median of days t-35..t-15 before the event).
Usage: python -I analysis/exp/er_presignal.py <path to Challenge3_Bad_Week_Radar>
Writes analysis/out/er_presignal.json. scripts/reproduce.sh runs it.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
d = pd.read_csv(Path(sys.argv[1]).expanduser() / "synthetic_data" / "synthetic_daily.csv",
                usecols=["patient_id", "day_in_program", "steps", "resting_heart_rate", "events"])
d["er"] = d.events.fillna("").str.contains("ER visit|admitted to hospital").astype(int)
rows = []
for pid, g in d.groupby("patient_id"):
    g = g.set_index("day_in_program")
    for day in g.index[g.er == 1]:
        if day < 40 or g.er.loc[day - 30:day - 1].sum() > 0:
            continue
        base = g.loc[day - 35:day - 15, ["steps", "resting_heart_rate"]].median()
        for k in range(1, 15):
            if day - k in g.index:
                r = g.loc[day - k, ["steps", "resting_heart_rate"]] - base
                rows.append({"days_before": k, "steps": r.steps, "rhr": r.resting_heart_rate})
x = pd.DataFrame(rows).groupby("days_before").agg(steps=("steps", "mean"), rhr=("rhr", "mean"), n=("steps", "size"))
out = {"events": int(x.n.max()), "by_days_before": {int(k): {"steps_vs_baseline": round(float(r.steps), 0),
       "resting_hr_vs_baseline_bpm": round(float(r.rhr), 2)} for k, r in x.iterrows()},
       "days_1_to_7_mean": {"steps": round(float(x.loc[1:7, "steps"].mean()), 0), "rhr_bpm": round(float(x.loc[1:7, "rhr"].mean()), 2)}}
(ROOT / "analysis" / "out" / "er_presignal.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=1))
