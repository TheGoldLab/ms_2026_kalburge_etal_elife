Analysis code for:

**Human decision-makers terminate evidence accumulation using flexible decision rules**

Kalburge I, Dallstream A, Josić K, Kilpatrick ZP, Ding L, Gold JI

---

## Setup

1. **Install** (Python ≥ 3.13, with [uv](https://github.com/astral-sh/uv)): `uv sync`
2. **Unpack the raw data**: `scripts/unpack_data.sh`. This extracts the frozen archive
   `data/pigeon_raw_human.tar.gz` into `../Data/Raw/Human` (a `Data/Raw/Human` directory next
   to this repo, not inside it), where `pigeon/pathDefaults.py` expects it. Safe to re-run.
   The archive is de-identified: each participant is a code (`OL-S001`, `CP26-S012`, ...) in the
   file name and the `participant` column, and Prolific IDs are removed.
3. **Run the model fits** (below), then the figure notebooks.

**Tests** (`tests/`, one file per package module; each file's docstring says what it covers):

- `uv run pytest`: the fast tests (about 10 s). Run after any change to the package.
- `uv run pytest -m slow`: the 13 stopping-model fit tests, which simulate data from known
  parameters and check that the fits recover them (about an hour).
- `uv run pytest -m ""`: everything.

Lint and format the package, scripts and tests only: `uv run ruff check --fix pigeon scripts tests`,
`uv run ruff format pigeon scripts tests`. Without the paths, ruff also rewrites the notebooks and the task code.

---

## Pipeline

Figures 3–6 rest on a trial-level **stopping model** (`pigeon/stopping.py`): a bound that falls
from a high start to a plateau and then declines slowly, varies from trial to trial, and is
compared with the perceived (noisy) position, plus guesses, anticipations and lapses; the
non-decision time (1 or 2 steps) is marginalized. Fits take hours, so they run as scripts and
are cached in `data/processed/` (not tracked by git). Run scripts from the project root, e.g.
`PYTHONPATH=. nohup caffeinate -i uv run python scripts/run_stopping_fits.py > data/processed/stopping_fits.log 2>&1 &`.

| Step | Script | Output (`data/processed/`) | Used by |
|---|---|---|---|
| 1 | `run_stopping_fits.py main` | `stopping_fits_main.pkl` | Figs 3, 3S1–3S6, 4, 5, 5S1 |
| 2 | `run_stopping_fits.py <variants>` (alternatives; see the script) | `stopping_fits_<variant>.pkl` | Fig 3S1 |
| 2 | `run_stopping_fits.py mx_by_snr` | `stopping_fits_mx_by_snr.pkl` | Fig 5 |
| 3 | `run_stopping_bootstrap.py` (after 1) | `stopping_bootstrap.pkl` | Figs 3S1, 4 |
| 3 | `run_stopping_late_slope.py` (after 1) | `stopping_late_slope.pkl` | Fig 5S1 |
| 3 | `run_optimal_collapse.py` (after 1: reads the mean NDT) | `optimal_collapse.pkl` | Fig 5S3 |
| 4 | `run_stopping_fits_cp.py cp_plateau_pair` | `stopping_fits_cp_plateau_pair.pkl` | step 5 |
| 5 | `run_stopping_fits_cp_matched.py` (after 4) | `stopping_fits_cp_matched.pkl` | Fig 6 |
| 5 | `run_cp_incentive_sims.py` (after 4) | `cp_incentive_step.pkl`, `cp_incentive_slope.pkl` | Fig 6 |
| 5 | `run_reward_incentives.py` (after 1 and 4: reads the mean NDTs) | `reward_incentives.pkl` | Fig 8 |

The bound bias correction (`pigeon.data.apply_bias_corrections`) is archived: no figure uses the
corrected bound (the stopping model works on raw positions), so `notebooks/archive/Make_biasCorrection.ipynb`
and its calibrations (`data/processed/archive/boundBiasCorrection*.mat`) are kept for reference only.

Run a notebook from `notebooks/`, e.g.
`OMP_NUM_THREADS=1 uv run jupyter nbconvert --to notebook --execute --inplace Figure03_boundSummary.ipynb`.
Figures are saved (PDF and PNG) to `../Figures`.

Table 1 (task settings of every cohort and block, n started and finished) is built by
`PYTHONPATH=. uv run python scripts/make_table1.py`, which writes `../Figures/Table01.xlsx`.

---

## Notebooks

| Notebook | Contents |
|---|---|
| `Figure02_performanceSummary` | Example trajectories, NDT congruence, accuracy vs. median DT with the ideal observer (cohort 1) |
| `Figure02S01_RRSummary` | Reward rate as % of the best fixed bound's, all blocks of both cohorts |
| `Figure03_boundSummary` | The direct bound measure vs. the stopping model's bound; bound shape; sources of commitments |
| `Figure03S01_modelComparison` | Model comparison (ΔAIC vs. alternative stopping models) and parameter recovery (bootstrap) |
| `Figure03S02_modelFitQuality` | RT distributions and accuracy vs. RT, data vs. model |
| `Figure03S03_suboptimalBehavior` | Trial-by-trial choice prediction vs. guess + lapse fraction; incongruent choices and premature crossings, data vs. model, and their sources in the model |
| `Figure03S04_stepsBeforeDecision` | Last and penultimate steps before the decision, data vs. model |
| `Figure03S05_sequentialStructure` | Trial-to-trial variability of the measured bound and post-error change, data vs. model |
| `Figure03S06_conditionalAccuracy` | Conditional accuracy functions, data vs. model |
| `Figure04_RRvsBound` | Bound plateau vs. reward rate with the fixed-bound optimum; within-block adaptation |
| `Figure04S01_RRvsBoundPD` | The same for the predefined-bound task |
| `Figure05_mixedVsBlockedSNR` | Low- vs. high-SNR bound plateaus, blocked vs. mixed SNR, on reward-rate surfaces |
| `Figure05S01_collapseByCondition` | Late bound slope (after the transition) in every condition |
| `Figure05S02_blockedSNRPD` | Low- vs. high-SNR bounds in the predefined-bound task (Figure 5's top row for PD) |
| `Figure05S03_optimalCollapse` | Optimal bound over the trial with zero-SNR trials mixed in, and its gain over the best flat bound (data: `scripts/run_optimal_collapse.py`) |
| `Figure06_cpSummary` | Change-point task: anticipation and step of the bound vs. matched fixed blocks, with reward-rate incentives |
| `Figure08_rewardRateIncentives` | How many blocks an ideal participant would need to tell each bound policy from the best, with participants' bounds (penalty, mixed-SNR and change-point blocks); a slot for the reward-change task |
| `Explore_NDT` | How `get_bounds` estimates the NDT |
| `Explore_boundDefinition` | How `get_bounds` defines the bound at the commit step (peak-step rule) |
| `Explore_trialQuality` | Congruence vs. RT: why the shortest trials are filtered from the direct bound measure |
| `Explore_subjectRawData` | One change-point subject's bounds and step trajectories, all four blocks |
| `Design_cpSNRs` | How the SNRs of the 2026 change-point cohort (0.2 and 0.6) were chosen |
| `Design_rcTask` | Ideal-observer bounds for the reward-change (RC) task design |

`notebooks/archive/` holds notebooks that no longer produce a figure (see its README).

---

## Repository layout

| Directory | Contents |
|---|---|
| `pigeon/` | The analysis package (below) |
| `notebooks/` | Figure notebooks; `Explore_` (analyses behind methods choices, data exploration) and `Design_` (task design) notebooks |
| `scripts/` | Model-fitting and simulation scripts (Pipeline) and `unpack_data.sh` |
| `tests/` | Tests of the package (Setup) |
| `data/` | The raw-data archive, and processed outputs in `data/processed/` |
| `task/` | Task code participants ran: `OL-MX-PD/` (cohorts 1 and 2, predefined bound), `MXSC/` (change point), `RC/` (reward change, not yet collected); see each folder's README |

Raw data (unpacked into `../Data/Raw/Human/`): one folder of per-subject CSVs per task: `OL`
(cohort 1, blocked SNR), `MX` (cohort 2, mixed SNR), `PD` (predefined bound), `MXSC` (change
point). `get_data_table(task_type=...)` reads the folder of that name.

---

## Package (`pigeon/`)

| Module | Contents |
|---|---|
| `data.py` | `get_data_table` (load trials), `get_bounds` (direct bound measure, NDT, DT, RT cutoffs), `get_good_trial_array` (standard trial filter), `apply_bias_corrections`, summaries |
| `stopping.py` | The stopping model: likelihood, `fit_stopping_model(s)`, simulation, `get_stopping_model_trials` (the trial selection for all fits) and helpers for the Figure 3 comparisons |
| `adaptation.py` | Within-block adaptation time constants (τ) and trial-to-trial structure of the bound |
| `simulation.py` | Fixed-bound simulations of whole blocks (reward-rate benchmarks) and of single trials (bias calibration) |
| `ideal_observer.py` | Reward-rate-optimal bounds by dynamic programming (RC task design) |
| `incentives.py` | Reward-rate moments of bound policies (ideal participant) and their discriminability from the best policy within a block |
| `plotting.py` | Shared figure style: fonts and sizes, color roles, panel letters, p and ρ formatting |
| `pathDefaults.py` | All file and directory paths |
