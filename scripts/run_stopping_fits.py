"""Fit the stopping model (pigeon.stopping) to the OL and MX blocks.

Writes data/processed/stopping_fits_<variant>.pkl (one row per subject x
condition, with a ``task`` column) for notebooks/Test_stoppingModel.ipynb.
Fits take minutes per subject, so they run here rather than in the notebook.

Trials come from pigeon.stopping.get_stopping_model_trials: raw block
numbering (OL blocks 1-6, each a single SNR; MX blocks 1-3, mixed SNR, the
blocks combine_snr=True keeps), trial_number >= 10, a recorded choice, and the
adaptation-tau exclusion used by the figure notebooks. Exclusions are printed.

Run from the project root, detached:

    nohup uv run python scripts/run_stopping_fits.py [variant ...] > data/processed/stopping_fits.log 2>&1 &

Variants (default: main):
    main            bound scale, CV and time course per block; guess, lapse,
                    anticipation, sensory noise and NDT {1, 2} shared
    shared_tc       time course shared across blocks
    flat            no time course (constant bound)
    per_block_rates guess, lapse and anticipation rates per block
    ndt123          NDT {1, 2, 3}
    no_noise        sensory_std fixed at 0
"""

import sys
import time
from pathlib import Path

import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}
VARIANTS = {
    "main": {},
    "shared_tc": {"time_course": "shared"},
    "flat": {"time_course": "flat"},
    "per_block_rates": {"shared_params": ()},
    "ndt123": {"ndt_values": (1, 2, 3)},
    "no_noise": {"fixed": {"sensory_std": 0.0}},
}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main(variants):
    tables = {task: get_stopping_model_trials(task, blocks) for task, blocks in DATASETS.items()}
    for variant in variants:
        kwargs = VARIANTS[variant]
        parts = []
        for task, d in tables.items():
            t0 = time.time()
            f = fit_stopping_models(d, group_col="condition", **kwargs).assign(task=task)
            n_bad = int((~f.groupby("subject_index").success.first()).sum())
            log(f"{variant} {task}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
                f"{n_bad} did not converge")
            parts.append(f)
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        pd.concat(parts, ignore_index=True).to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["main"])
