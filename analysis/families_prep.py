"""Write train-fit-patient rows (features + targets + patient_id) for the PyCaret first pass. Val/test never included."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import research as R

d, F = R.base()
fit, carve, va = R.splits(d)
out = R.CACHE
use = ((d.in_episode == 0) & (d.day_in_program >= 14) & d.patient_id.isin(fit)).values
use2 = ((d.day_in_program >= 14) & (d.groupby("patient_id").er.transform(lambda v: v.rolling(7, min_periods=1).sum()) == 0)
        & d.patient_id.isin(fit)).values
rng = np.random.default_rng(7)
for name, m, tgt in (("rough", use, "target"), ("er", use2, "er_ahead")):
    X = F[m].copy()
    X["patient_id"] = d.patient_id[m].values
    X["y"] = d[tgt][m].astype(int).values
    pos, neg = X[X.y == 1], X[X.y == 0]
    n = 150_000
    k = int(n * len(pos) / len(X))
    s = pd.concat([pos.sample(min(k, len(pos)), random_state=7), neg.sample(n - min(k, len(pos)), random_state=7)])
    s.to_parquet(out / f"pyc_{name}.parquet")
    print(name, len(X), "->", len(s), "pos rate", round(s.y.mean(), 4), "patients", s.patient_id.nunique())
