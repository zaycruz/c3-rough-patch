# Data

Nothing in this folder is committed except this file. The sponsor data stays out of git.

## Sponsor bundle (required)

Get the challenge folder **Challenge3_Bad_Week_Radar** from the eMerge hackathon organizers (Sylvester Comprehensive Cancer Center, Crane Lab). Unzip it here so the paths below exist, or pass its location as the first argument to `scripts/reproduce.sh`.

| Path under `data/Challenge3_Bad_Week_Radar/` | Used by | sha256 |
|---|---|---|
| `synthetic_data/synthetic_daily.csv` (48.3 MB, 465,466 rows) | `analysis/train.py`, `analysis/exp/er_presignal.py` | `6d9b500ed5fa41ce0eb0f847351abf238623e90d20d534df0c7ea1774eb2a3b7` |
| `synthetic_data/synthetic_patients.csv` (3,000 people) | `analysis/train.py` | `81a65878cf4e8ff04d1986b9b874d67acae129732e3e5a700943b5a98151cc18` |
| `fatigue_study_daily.csv` (real, 9,317 rows) | `analysis/real_check.py` | `8ed37e47cf37ddbef74266f350a1112437af80bc9496e1f74be33d55ae71dc2b` |

`scripts/reproduce.sh` checks these three hashes first and stops if any differ.

The bundle also ships these files. C3 does not read them:

| File | sha256 |
|---|---|
| `README.md` | `41ba0c3f17f6384a14486c13cb0c99b417280f40d84982a0b438111be13a4d2d` |
| `lifesnaps_daily.csv` | `25cd236a6c47c31bc1e81668b348c9ca99fdcc55b81e8b88452b1452d936c861` |
| `lifesnaps_hourly.csv` | `e1a45303eef76b42ed425b5523c5d4980d625bae472ae583b1db0d78096e18cb` |
| `synthetic_data/synthetic_hourly_250_patients.csv` | `6bb40eeb310eaaa6fb4f76151ce7c072201f085643abc18a4a2ea373900183e2` |
| `synthetic_data/synthetic_250_patients.json` | `2abf2cf6dcbfdcd94cc98cb39968e081f8328778093dee86dde57fbb346393cd` |
| `synthetic_data/README.txt` | `873888667a29ff441e73b80428264776ca94fa13be0f4faec16b976f88bfb1c4` |

## Where the real data comes from

The real file is a cleaned subset prepared by the organizers, so the raw public downloads **will not match the hashes above**. To reproduce, use the sponsor bundle.

- **Fatigue study** (`fatigue_study_daily.csv`): Rao C, et al. *Association of digital measures and self-reported fatigue.* Frontiers in Digital Health, 2023. The data is from Evidation, Novartis and Roche. It is on Zenodo: https://zenodo.org/records/8018238. See that record for its terms of access.
- **LifeSnaps** (shipped, not used by C3): Yfantidou S, et al. *Scientific Data*, 2022. CC BY 4.0. https://zenodo.org/records/7229547

C3 uses no other public dataset (no MEPS, NHANES, CGMacros or AnnoMI).
