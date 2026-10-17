"""Label cross-check at a matched budget (README "Cross-check, so the new label is not grading itself").

Historical: it reads the scored.parquet written by train.py at commit d72545d (label v2, wearable + schedule model,
before check-ins were inputs), which also scores a model trained on the v1 label (score_model_v1label).
Usage: python -I analysis/exp/label_crosscheck.py <dir holding train.py and out/scored.parquet>
Writes <dir>/out/label_crosscheck.json. scripts/reproduce.sh runs it.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

A = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(A))
import train as T  # noqa: E402  (train.py from d72545d)

BUDGET = 0.12
d = pd.read_parquet(A / "out" / "scored.parquet")
va, te = d[d.split == "val"], d[d.split == "test"]
res = {}
for name, fr in (("v2_onsets", lambda x: x),
                 ("v1_onsets", lambda x: x.assign(onset=x.onset_v1, in_episode=x.in_episode_v1, target=x.target_v1))):
    v, t = fr(va), fr(te)
    q = v[(v.in_episode == 0) & (v.day_in_program >= 14)]
    res[name] = {}
    for k in ("score_model", "score_model_v1label", "score_schedule"):
        thr = float(np.quantile(q[k], 1 - BUDGET))
        e, w = T.episode_metrics(t, k, thr), T.week_metrics(t, k, thr)
        res[name][k] = dict(week_auc=w["auc"], episode_recall=e["episode_recall"], alert_precision=e["alert_precision"],
                            alerts_per_patient_month=e["alerts_per_patient_month"], er_recall=e["er_recall"],
                            median_lead_days=e["median_lead_days"])
(A / "out" / "label_crosscheck.json").write_text(json.dumps({"budget": BUDGET, **res}, indent=2))
print(json.dumps(res, indent=1))
