Analysis code for:

**Human decision-makers terminate evidence accumulation using flexible decision rules**

Kalburge I, Dallstream A, Josić K, Kilpatrick ZP, Ding L, Gold JI

---

## Setup

1. **Update data paths** in [pigeon/pathDefaults.py](pigeon/pathDefaults.py):
   - `RAW_DATA_DIR` — top-level directory containing `Pigeon_OL/`, `Pigeon_MX/`, etc.
   - `DATA_DIR` — directory for processed outputs (bias correction file, RR matrices)
   - `FIGURES_DIR` — directory where figures are saved

2. **Install dependencies** (Python ≥ 3.13):
   ```
   pip install -e .
   ```
   Or with [uv](https://github.com/astral-sh/uv): `uv sync`

3. **Run preprocessing notebooks** (must run before Figure notebooks):
   - `notebooks/Make_biasCorrection.ipynb` — generates `boundBiasCorrection.mat`
   - `notebooks/Make_RRMatrix.ipynb` — generates `RRMats.mat` and `RRMats_OL.mat`

4. **Run Figure notebooks** to reproduce paper figures.

---

## Notebook index

### Preprocessing
| Notebook | Output | Description |
|---|---|---|
| `Make_biasCorrection` | `boundBiasCorrection.mat` | Bias-correction calibration for the bound estimator |
| `Make_RRMatrix` | `RRMats.mat`, `RRMats_OL.mat` | Expected reward-rate matrices over bound grids |

### Main figures
| Notebook | Figure | Description |
|---|---|---|
| `Figure02_performanceSummary` | Figure 02 | OL task performance: example trajectories, congruence, accuracy vs. DT |
| `Figure02S01_RRSummary` | Figure 02S1 | Reward-rate summary |
| `Figure03_boundSummary` | Figure 03 | Bound vs. DT: individual trials, z-scored curves, regression slopes |
| `Figure03S01_congruenceByRT` | Figure 03S1 | Congruence by response time |
| `Figure03S02_boundTest` | Figure 03S2 | Bound definition validation |
| `Figure04_RRvsBound` | Figure 04 | Reward rate vs. bound (OL) and within-block learning curves |
| `Figure05_mixedVsBlockedSNR` | Figure 05 | Bound comparison: mixed vs. blocked SNR |
| `Figure05S01_boundDiffByDT` | Figure 05S1 | Hi−Lo SNR bound difference by DT |
| `Figure05S02_RRMapExploration` | Figure 05S2 | Reward-rate map exploration |
| `Figure06_cpSummary` | Figure 06 | Change-point task: bound adaptation relative to optimal |
| `Figure07_biasCorrection` | Figure 07 | Bias correction example (DT=2, lowest SNR) |
| `Table_slopeAnalyses` | Table | Linear-regression slope statistics |

### Tests and diagnostics
| Notebook | Description |
|---|---|
| `Test_NDT` | NDT consistency across SNR conditions and blocks |
| `Test_boundDefinition` | Validation of the bound-inference algorithm |
| `Test_cpData` | Change-point data quality checks |
| `Test_trialQuality` | Trial quality filter validation |

---

## Package structure (`pigeon/`)

| Module | Description |
|---|---|
| `data.py` | Load CSV data, infer bounds/DT/RT, apply bias correction |
| `stats.py` | Per-subject/block/SNR summaries (performance, bound statistics) |
| `simulate.py` | Generative model: random-walk accumulator with absorbing bound |
| `pathDefaults.py` | All project-wide file and directory paths |

Key functions:
- `get_data_table(task_type)` — load all trials for `'OL'`, `'MX'`, or `'PD'`
- `get_bounds(steps_list, choices)` — infer bound, DT, RT from step sequences
- `get_good_trial_array(data_table)` — standard quality filter (DT≥2, trial≥10, no wall hits)
- `get_bound_summary(data_table)` — mean |bound| per subject/block/SNR/DT bin
- `get_performance_summary(data_table)` — accuracy and DT statistics
- `simulate_trials(...)` — core simulation engine
- `get_simulated_data_table(...)` — full simulated data table matching `get_data_table` format

The CP (change-point) task is not implemented in Python; use the MATLAB pipeline to generate pre-computed summaries (`boundSummaries_wCP.mat`) consumed by `Make_RRMatrix` and `Figure06`.
