"""PyCaret first pass: compare_models on TRAIN patients only, GroupKFold by patient (5 folds), sorted by AUC."""
import sys
from pathlib import Path
import pandas as pd
from pycaret.classification import setup, compare_models, pull

name = sys.argv[1]
df = pd.read_parquet(Path(__file__).resolve().parent / "out" / "research" / f"pyc_{name}.parquet")
setup(data=df, target="y", train_size=0.999, fold_strategy="groupkfold", fold_groups="patient_id", fold=5,
      ignore_features=["patient_id"], data_split_shuffle=False, data_split_stratify=False,
      session_id=7, verbose=False, n_jobs=-1, html=False)
compare_models(sort="AUC", n_select=3, exclude=["svm", "gpc", "rbfsvm", "knn", "qda", "lda", "nb", "ridge"],
               budget_time=12)
lb = pull()
lb.to_csv(Path(__file__).resolve().parent / "out" / "research" / f"pyc_leaderboard_{name}.csv")
print(lb[["Model", "AUC", "Prec.", "Recall", "F1", "TT (Sec)"]].head(10).to_string())
