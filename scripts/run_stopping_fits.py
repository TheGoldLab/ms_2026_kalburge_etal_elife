"""Fit the stopping model (pigeon.stopping) to the fixed blocks of OL, MX and MXSC.

Writes data/processed/stopping_fits_<variant>.pkl (one row per subject x
condition, with a ``task`` column) for notebooks/Test_stoppingModel.ipynb.
Fits take minutes per subject, so they run here rather than in the notebook.

Conditions: OL by (block, SNR) cell (SNR was blocked, and get_data_table
merges each pair of blocked-SNR blocks); MX by block (SNR mixed within a
block); MXSC fixed blocks 1 (Low) and 2 (High). Trials: trial_number >= 10 and
a recorded choice; exclusions are printed.

Run from the project root, detached:

    nohup uv run python scripts/run_stopping_fits.py [variant ...] > data/processed/stopping_fits.log 2>&1 &

Variants (default: main):
    main        time_course='shared', NDT {1, 2}, sensory noise free
    flat        time_course='flat'
    per_group   time_course='per_group'
    ndt123      NDT {1, 2, 3}
    no_noise    sensory_std fixed at 0
"""

import sys
import time
from pathlib import Path

import pandas as pd

from pigeon import get_data_table
from pigeon.stopping import fit_stopping_models

OUT_DIR = Path("data/processed")
MIN_TRIAL_NUMBER = 10
DATASETS = {"OL": [1, 2, 3], "MX": [1, 2, 3], "MXSC": [1, 2]}
VARIANTS = {
    "main": {},
    "flat": {"time_course": "flat"},
    "per_group": {"time_course": "per_group"},
    "ndt123": {"ndt_values": (1, 2, 3)},
    "no_noise": {"fixed": {"sensory_std": 0.0}},
}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def load_fixed_blocks(task, blocks):
    """Selected fixed-block trials with a ``condition`` column; prints exclusions."""
    d = get_data_table(task_type=task, correct_bias=None)
    d = d[d.block_index.isin(blocks)]
    l_early = d.trial_number < MIN_TRIAL_NUMBER
    l_nochoice = d.choice.isna()
    log(f"{task}: {len(d):,} trials in blocks {blocks}; excluded {l_early.sum():,} with trial_number < "
        f"{MIN_TRIAL_NUMBER}, {(l_nochoice & ~l_early).sum():,} more with no choice; "
        f"{d.subject_index.nunique()} subjects")
    d = d[~l_early & ~l_nochoice].copy()
    lev = d.snr.abs().round(3)
    if task == "OL":
        d["condition"] = [f"B{b:.0f} SNR {s:g}" for b, s in zip(d.block_index, lev)]
    else:
        d["condition"] = [f"B{b:.0f}" for b in d.block_index]
    return d


def main(variants):
    tables = {task: load_fixed_blocks(task, blocks) for task, blocks in DATASETS.items()}
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
