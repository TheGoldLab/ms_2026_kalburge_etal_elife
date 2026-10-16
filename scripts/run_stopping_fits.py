"""Fit the stopping model (pigeon.stopping) to the OL and MX blocks.

Writes data/processed/stopping_fits_<variant>.pkl (one row per subject x
condition, with a ``task`` column). ``main`` is the model of Figures 3-5;
the other variants are the alternatives compared in Figure03S01 (OL), and
``mx_by_snr`` gives the per-SNR plateaus of Figure 5 (MX). Fits take minutes
per subject, so they run here rather than in the notebooks.

Trials come from pigeon.stopping.get_stopping_model_trials: raw block
numbering (OL blocks 1-6, each a single SNR; MX blocks 1-3, mixed SNR),
trial_number >= 10, a recorded choice, and the adaptation-transient
exclusion. Exclusions are printed.

Run from the project root, detached:

    PYTHONPATH=. nohup caffeinate -i uv run python scripts/run_stopping_fits.py [variant ...] \
        > data/processed/stopping_fits.log 2>&1 &

Variants (default: main):
    main            bound plateau and CV, guess, lapse and anticipation rates per
                    block; knee-form time course, sensory noise and NDT {1, 2}
                    shared (fit_stopping_model's defaults)
    knots           as main but the time course through fixed knots at steps 1/6/16
    per_block_tc    time course per block
    flat            no time course (constant bound)
    shared_rates    guess, lapse and anticipation rates shared across blocks
    ndt123          NDT {1, 2, 3}
    no_noise        sensory_std fixed at 0
    flat_guess_tc   constant bound; guess rate varies over the trial (shared
                    shape per subject, fixed knots, same penalty as the bound)
    knee_flat       bound flat after the knee
    mx_by_snr       MX only: every per-block parameter separate per block x SNR
                    (groups 'B<block>_lo' / 'B<block>_hi')
    tc_by_snr       as main but one time-course shape per SNR (column
                    'snr_level', lo/hi; OL blocks 1-3 vs 4-6, MX trials by
                    SNR within the mixed blocks)
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}
VARIANTS = {
    "main": {},
    "knots": {"time_course_form": "knots"},
    "per_block_tc": {"time_course": "per_group"},
    "flat": {"time_course": "flat"},
    "shared_rates": {"shared_params": ("guess_rate", "lapse_rate", "anticipation_rate")},
    "ndt123": {"ndt_values": (1, 2, 3)},
    "no_noise": {"fixed": {"sensory_std": 0.0}},
    "flat_guess_tc": {"time_course": "flat", "guess_time_course": "shared"},
    "knee_flat": {"time_course_form": "knee", "fixed": {"late_slope": 0.0}},
    "mx_by_snr": {"group_col": "condition_snr", "tasks": ["MX"]},
    "tc_by_snr": {"time_course_col": "snr_level"},
}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main(variants):
    tables = {task: get_stopping_model_trials(task, blocks) for task, blocks in DATASETS.items()}
    for d in tables.values():
        # Lowest |snr| in the dataset is 'lo'; OL raw blocks have one SNR each.
        lo = np.isclose(d["snr"].abs(), d["snr"].abs().min())
        d["snr_level"] = np.where(lo, "lo", "hi")
        d["condition_snr"] = d["condition"] + "_" + d["snr_level"]
    for variant in variants:
        kwargs = dict(VARIANTS[variant])
        tasks = kwargs.pop("tasks", list(tables))
        kwargs.setdefault("group_col", "condition")
        parts = []
        for task in tasks:
            d = tables[task]
            t0 = time.time()
            f = fit_stopping_models(d, **kwargs).assign(task=task)
            n_bad = int((~f.groupby("subject_index").success.first()).sum())
            log(
                f"{variant} {task}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
                f"{n_bad} did not converge"
            )
            parts.append(f)
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        pd.concat(parts, ignore_index=True).to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["main"])
