"""Parametric bootstrap of the stopping model on the real OL and MX subjects.

Simulates every subject from their own main-variant fit
(data/processed/stopping_fits_main.pkl), on their real trial structure (same
blocks, trial counts, SNRs and step statistics), refits the simulated data
with the same defaults, and saves true vs. fitted parameters. This checks
whether sensory noise, bound variability (CV) and guessing can be told apart
for these subjects at their own parameter values, rather than over generic
recovery ranges.

Writes data/processed/stopping_bootstrap.pkl (one row per subject x block).
Run from the project root (after run_stopping_fits.py main):

    nohup uv run python scripts/run_stopping_bootstrap.py > data/processed/stopping_bootstrap.log 2>&1 &
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials, simulate_stopping_data_table

PROCESSED = Path("data/processed")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}
SEED = 20261010
PARAMS = ["bound_scale", "bound_cv", "guess_rate", "lapse_rate", "anticipation_rate",
          "sensory_std", "ndt_p1", "log_h_k1", "log_h_k16"]


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main():
    fits = pd.read_pickle(PROCESSED / "stopping_fits_main.pkl")
    rng = np.random.default_rng(SEED)
    out = []
    for task, blocks in DATASETS.items():
        d = get_stopping_model_trials(task, blocks)
        f_true = fits[fits.task == task]
        sim = simulate_stopping_data_table(d, f_true, group_col="condition", num_reps=1, rng=rng)
        t0 = time.time()
        f_fit = fit_stopping_models(sim, group_col="condition")
        log(f"{task}: refit {f_fit.subject_index.nunique()} simulated subjects in {(time.time() - t0) / 60:.1f} min; "
            f"{int((~f_fit.groupby('subject_index').success.first()).sum())} did not converge")
        m = f_true[["subject_index", "group"] + PARAMS].merge(
            f_fit[["subject_index", "group", "success"] + PARAMS], on=["subject_index", "group"],
            suffixes=("_true", "_fit"))
        out.append(m.assign(task=task))
    pd.concat(out, ignore_index=True).to_pickle(PROCESSED / "stopping_bootstrap.pkl")
    log("wrote data/processed/stopping_bootstrap.pkl")


if __name__ == "__main__":
    main()
