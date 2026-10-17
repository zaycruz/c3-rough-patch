# Radar research log (validation patients only; thresholds on a train carve-out)

| # | idea | val ep. recall | val ER recall | val week AUC | val week precision | val week recall | alerts/pt/mo | kept? |
|---|---|---|---|---|---|---|---|---|
| 0 | base (current Radar, 39bc5f8) | 0.609 | 0.44 | 0.782 | 0.15 | 0.362 | 0.82 |  |
| 1 | schedule-only GBM (reference baseline) | 0.538 | 0.39 | 0.769 | 0.14 | 0.35 | 0.63 |  |
| 2 | base+trend14 | 0.645 | 0.53 | 0.785 | 0.153 | 0.37 | 0.81 |  |
| 3 | base+prevcycle | 0.607 | 0.47 | 0.788 | 0.152 | 0.377 | 0.8 |  |
| 4 | base+engage | 0.614 | 0.49 | 0.786 | 0.156 | 0.384 | 0.83 |  |
| 5 | base+inter | 0.598 | 0.41 | 0.785 | 0.152 | 0.357 | 0.74 |  |
| 6 | base+phase | 0.625 | 0.48 | 0.783 | 0.149 | 0.353 | 0.85 |  |
| 7 | base+history | 0.629 | 0.51 | 0.785 | 0.16 | 0.391 | 0.8 |  |
| 8 | base+trend14+engage | 0.629 | 0.52 | 0.789 | 0.158 | 0.384 | 0.82 |  |
| 9 | base+trend14+engage+prevcycle | 0.647 | 0.55 | 0.788 | 0.157 | 0.379 | 0.79 |  |
| 10 | base+trend14+engage+prevcycle+history+phase | 0.634 | 0.55 | 0.792 | 0.148 | 0.37 | 0.81 |  |
| 11 | base+trend14+engage+prevcycle {"max_iter": 600, "learning_rate": 0.03, "max_leaf_nodes": 15, "l2_regularization": 1.0, "min_samples_leaf": 200} | 0.627 | 0.56 | 0.791 | 0.155 | 0.372 | 0.79 |  |
| 12 | base+trend14+engage+prevcycle {"max_iter": 400, "learning_rate": 0.05, "max_depth": 4, "min_samples_leaf": 100} | 0.636 | 0.51 | 0.79 | 0.152 | 0.377 | 0.78 |  |
| 13 | base+trend14+engage+prevcycle er_blend=0.3 | 0.549 | 0.63 | 0.778 | 0.141 | 0.319 | 0.76 |  |
| 14 | base+trend14+engage+prevcycle {"class_weight": "balanced"} | 0.634 | 0.51 | 0.787 | 0.153 | 0.379 | 0.77 |  |
| 15 | base+trend14+engage+prevcycle {"max_iter": 800, "learning_rate": 0.02, "max_leaf_nodes": 31, "l2_regularization": 1.0, "min_samples_leaf": 100} | 0.625 | 0.49 | 0.791 | 0.153 | 0.377 | 0.76 |  |
| 16 | [swap] base | 0.688 | 0.556 | 0.796 | 0.181 | 0.369 | 0.88 |  |
| 17 | [swap] base+trend14 | 0.72 | 0.667 | 0.799 | 0.195 | 0.397 | 0.89 |  |
| 18 | [swap] base+trend14+engage+prevcycle | 0.688 | 0.596 | 0.795 | 0.195 | 0.411 | 0.88 |  |
| 19 | [swap] base+trend14+engage+prevcycle+history | 0.701 | 0.646 | 0.798 | 0.205 | 0.411 | 0.9 |  |
| 20 | [swap] base {"_schedule_only": true} | 0.613 | 0.404 | 0.786 | 0.172 | 0.376 | 0.72 |  |
| 21 | base+trend14+history | 0.654 | 0.54 | 0.79 | 0.159 | 0.389 | 0.83 |  |
| 22 | [swap] base+trend14+history | 0.705 | 0.646 | 0.8 | 0.196 | 0.401 | 0.88 |  |
| 23 | [swap] base+trend14+engage | 0.691 | 0.626 | 0.793 | 0.184 | 0.381 | 0.89 |  |
| 24 | v2 integrated in train.py (sanity: should equal base+trend14+history) | 0.654 | 0.54 | 0.79 | 0.159 | 0.389 | 0.83 |  |

## Outcome

- Selection used two validation views (val patients; and, as a second opinion, the train carve-out with thresholds on val). Only `trend14` (14-day level + 7-day slope vs personal baseline) helped consistently in both: episode recall about +3.5 points, ER recall about +10 points. `history` (60-day crash memory) added a little AUC and precision. `prevcycle`, `phase`, `engage`, the interactions, class weights and GBM tuning were within noise. An ER-head blend traded episode recall for ER recall (-6 / +8 points), so it is a trade-off, not a win.
- Chosen: base + trend14 + history (row 24).
- One test run (750 held-out patients) vs 39bc5f8: week AUC 0.804 → 0.805, episodes caught 64% → 64%, ER/admissions caught 54% → 56%, week precision 20% → 20%. The validation gain mostly did **not** transfer: the 2 to 4 point differences on validation were within noise (val has about 100 ER events).
- Possible next step, not adopted: a separate ER/admission head for an "urgent" status tier, so the trade-off does not touch the rough-patch alert.

## Model families (validation only; thresholds on train carve-out)

- {"family": "hgb", "features": "v2", "task": "rough", "val_episode_recall": 0.654, "val_er_recall": 0.54, "val_week_auc": 0.79, "val_week_precision": 0.159, "alerts_ppm": 0.83}
- {"family": "lgbm", "features": "v2", "task": "rough", "val_episode_recall": 0.629, "val_er_recall": 0.52, "val_week_auc": 0.791, "val_week_precision": 0.154, "alerts_ppm": 0.79}
- {"family": "xgb", "features": "v2", "task": "rough", "val_episode_recall": 0.647, "val_er_recall": 0.57, "val_week_auc": 0.796, "val_week_precision": 0.166, "alerts_ppm": 0.78}
- {"family": "et", "features": "v2", "task": "rough", "val_episode_recall": 0.605, "val_er_recall": 0.47, "val_week_auc": 0.79, "val_week_precision": 0.154, "alerts_ppm": 0.73}
- {"family": "rf", "features": "v2", "task": "rough", "val_episode_recall": 0.632, "val_er_recall": 0.5, "val_week_auc": 0.795, "val_week_precision": 0.167, "alerts_ppm": 0.8}
- {"family": "lrspline", "features": "v2", "task": "rough", "val_episode_recall": 0.509, "val_er_recall": 0.51, "val_week_auc": 0.751, "val_week_precision": 0.138, "alerts_ppm": 0.62}
- {"family": "cnn", "features": "v2", "task": "rough", "val_episode_recall": 0.429, "val_er_recall": 0.47, "val_week_auc": 0.753, "val_week_precision": 0.136, "alerts_ppm": 0.41}
- {"family": "cnn", "features": "v2", "task": "rough", "val_episode_recall": 0.375, "val_er_recall": 0.41, "val_week_auc": 0.714, "val_week_precision": 0.12, "alerts_ppm": 0.52}
- {"family": "ens:hgb,xgb", "features": "v2", "task": "rough", "val_episode_recall": 0.641, "val_er_recall": 0.48, "val_week_auc": 0.795, "val_week_precision": 0.166, "alerts_ppm": 0.77}
- {"family": "ens:hgb,xgb,rf", "features": "v2", "task": "rough", "val_episode_recall": 0.643, "val_er_recall": 0.49, "val_week_auc": 0.797, "val_week_precision": 0.166, "alerts_ppm": 0.76}
- {"family": "hgb", "features": "main", "task": "rough", "val_episode_recall": 0.609, "val_er_recall": 0.44, "val_week_auc": 0.782, "val_week_precision": 0.15, "alerts_ppm": 0.82}
- {"family": "lgbm", "features": "main", "task": "rough", "val_episode_recall": 0.621, "val_er_recall": 0.5, "val_week_auc": 0.786, "val_week_precision": 0.153, "alerts_ppm": 0.8}
- {"family": "xgb", "features": "main", "task": "rough", "val_episode_recall": 0.627, "val_er_recall": 0.51, "val_week_auc": 0.788, "val_week_precision": 0.159, "alerts_ppm": 0.77}
- {"family": "rf", "features": "main", "task": "rough", "val_episode_recall": 0.618, "val_er_recall": 0.46, "val_week_auc": 0.792, "val_week_precision": 0.162, "alerts_ppm": 0.76}
- {"family": "hgb", "features": "main", "task": "er", "val_er_auc": 0.868, "val_er_ap": 0.0668, "val_day_recall_3pct": 0.182, "val_day_precision_3pct": 0.07, "val_er_event_recall": 0.49}
- {"family": "lgbm", "features": "main", "task": "er", "val_er_auc": 0.866, "val_er_ap": 0.0612, "val_day_recall_3pct": 0.194, "val_day_precision_3pct": 0.077, "val_er_event_recall": 0.48}
- {"family": "xgb", "features": "main", "task": "er", "val_er_auc": 0.867, "val_er_ap": 0.0575, "val_day_recall_3pct": 0.169, "val_day_precision_3pct": 0.069, "val_er_event_recall": 0.43}
- {"family": "rf", "features": "main", "task": "er", "val_er_auc": 0.866, "val_er_ap": 0.0609, "val_day_recall_3pct": 0.205, "val_day_precision_3pct": 0.082, "val_er_event_recall": 0.46}
- {"family": "hgb", "features": "v2", "task": "er", "val_er_auc": 0.864, "val_er_ap": 0.068, "val_day_recall_3pct": 0.205, "val_day_precision_3pct": 0.081, "val_er_event_recall": 0.54}
- {"family": "lgbm", "features": "v2", "task": "er", "val_er_auc": 0.867, "val_er_ap": 0.0686, "val_day_recall_3pct": 0.198, "val_day_precision_3pct": 0.081, "val_er_event_recall": 0.49}
- {"family": "xgb", "features": "v2", "task": "er", "val_er_auc": 0.87, "val_er_ap": 0.0675, "val_day_recall_3pct": 0.207, "val_day_precision_3pct": 0.081, "val_er_event_recall": 0.48}
- {"family": "rf", "features": "v2", "task": "er", "val_er_auc": 0.869, "val_er_ap": 0.0659, "val_day_recall_3pct": 0.198, "val_day_precision_3pct": 0.084, "val_er_event_recall": 0.47}
- {"family": "ens:hgb,xgb", "features": "v2", "task": "er", "val_er_auc": 0.87, "val_er_ap": 0.0717, "val_day_recall_3pct": 0.214, "val_day_precision_3pct": 0.084, "val_er_event_recall": 0.48}
- {"family": "ens:hgb,xgb,rf", "features": "v2", "task": "er", "val_er_auc": 0.876, "val_er_ap": 0.0728, "val_day_recall_3pct": 0.224, "val_day_precision_3pct": 0.089, "val_er_event_recall": 0.5}
- {"family": "lrspline", "features": "v2", "task": "er", "val_er_auc": 0.854, "val_er_ap": 0.056, "val_day_recall_3pct": 0.188, "val_day_precision_3pct": 0.08, "val_er_event_recall": 0.4}

### One test evaluation (ER task, winner vs HistGB)

- hgb main: {"test_er_auc": 0.858, "test_er_ap": 0.0566, "test_day_recall_3pct": 0.177, "test_day_precision_3pct": 0.079, "test_er_event_recall_2to7d": 0.467, "test_er_events": 182}
- hgb v2: {"test_er_auc": 0.851, "test_er_ap": 0.0585, "test_day_recall_3pct": 0.186, "test_day_precision_3pct": 0.083, "test_er_event_recall_2to7d": 0.445, "test_er_events": 182}
- ens hgb+xgb+rf v2: {"test_er_auc": 0.863, "test_er_ap": 0.0687, "test_day_recall_3pct": 0.196, "test_day_precision_3pct": 0.091, "test_er_event_recall_2to7d": 0.434, "test_er_events": 182}

> Outcome (both loops): nothing merged. Model families (PyCaret with patient-grouped folds, LightGBM, XGBoost, RF, ExtraTrees, spline logistic, a 1D-CNN on 28-day windows, ensembles) did not beat HistGB on rough patches. For ER only, a HistGB+XGB+RF ensemble ranked slightly better on test (AUC 0.863 vs 0.858) but caught fewer ER events (43% vs 47%). HistGB with the main features stays for both heads. Code on branch research/model-v2 (159c6e4).
