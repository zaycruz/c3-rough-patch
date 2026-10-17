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
