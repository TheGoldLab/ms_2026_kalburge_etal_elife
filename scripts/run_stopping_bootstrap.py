"""Parametric bootstrap of the stopping model on the real OL and MX subjects.

Simulates every subject NUM_REPS times from their own main-variant fit
(data/processed/stopping_fits_main.pkl), on their real trial structure (same
blocks, trial counts, SNRs and step statistics), refits each simulated data
set with the same defaults (one start, at the generating knee, rather than
the multi-start search), and saves true vs. fitted parameters. The spread
of a subject's refits gives a confidence interval on their parameters
(e.g. the bound plateau), and the agreement between simulated and refit
values shows which parameters can be told apart (e.g. sensory noise, bound
variability and guessing) at these subjects' own parameter values.

Writes data/processed/stopping_bootstrap.pkl (one row per subject x block x
replicate, column ``rep``), used by Figure03S01 (parameter recovery) and
Figure04 (error bars). Run from the project root (after run_stopping_fits.py main):

    nohup caffeinate -i uv run python scripts/run_stopping_bootstrap.py \
        > data/processed/stopping_bootstrap.log 2>&1 &
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials, simulate_stopping_data_table

PROCESSED = Path("data/processed")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}
SEED = 20261011
NUM_REPS = 10
PARAMS = [
    "bound_scale",
    "bound_cv",
    "guess_rate",
    "lapse_rate",
    "anticipation_rate",
    "sensory_std",
    "ndt_p1",
    "log_h_start",
    "knee",
    "late_slope",
]


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main():
    fits = pd.read_pickle(PROCESSED / "stopping_fits_main.pkl")
    rng = np.random.default_rng(SEED)
    out = []
    for task, blocks in DATASETS.items():
        d = get_stopping_model_trials(task, blocks)
        f_true = fits[fits.task == task]
        sim = simulate_stopping_data_table(d, f_true, group_col="condition", num_reps=NUM_REPS, rng=rng)
        # Each replicate is fit as its own subject-session (ids subject * 100 + rep).
        sim["subject_index"] = sim["subject_index"] * 100 + sim["rep"]
        t0 = time.time()
        # Each refit starts once, at the knee that generated it, instead of from KNEE_STARTS (a third of the time).
        knees = f_true.groupby("subject_index").knee.first()
        starts = {s: {"knee_starts": (float(knees[s // 100]),)} for s in sim["subject_index"].unique()}
        f_fit = fit_stopping_models(sim, group_col="condition", subject_kwargs=starts)
        log(
            f"{task}: refit {f_fit.subject_index.nunique()} simulated sessions in {(time.time() - t0) / 60:.1f} min; "
            f"{int((~f_fit.groupby('subject_index').success.first()).sum())} did not converge"
        )
        f_fit["rep"] = f_fit["subject_index"] % 100
        f_fit["subject_index"] = f_fit["subject_index"] // 100
        m = f_true[["subject_index", "group"] + PARAMS].merge(
            f_fit[["subject_index", "group", "rep", "success"] + PARAMS],
            on=["subject_index", "group"],
            suffixes=("_true", "_fit"),
        )
        out.append(m.assign(task=task))
    pd.concat(out, ignore_index=True).to_pickle(PROCESSED / "stopping_bootstrap.pkl")
    log("wrote data/processed/stopping_bootstrap.pkl")


if __name__ == "__main__":
    main()
