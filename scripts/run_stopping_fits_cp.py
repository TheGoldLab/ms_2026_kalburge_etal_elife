"""Fit the stopping model (pigeon.stopping) to the change-point (MXSC) cohort.

Writes data/processed/stopping_fits_cp_<variant>.pkl (one row per subject x
block) for the Figure 6 rebuild. Every subject with all four blocks is fit
jointly over them: block 1 (fixed low SNR), block 2 (fixed high SNR), block 3
(LowHigh change point) and block 4 (HighLow change point). As in the OL/MX
main model, bound plateau and CV, guess, lapse and anticipation rates are per
block, and the knee-form time course, sensory noise and NDT {1, 2} are shared,
so the fixed blocks anchor the subject's within-trial collapse and any
post-change-point term measures change beyond it.

Trials come from pigeon.stopping.get_stopping_model_trials (trial_number >= 10,
adaptation-transient exclusion, recorded choice). Exclusions are printed.

Run from the project root, detached:

    PYTHONPATH=. nohup caffeinate -i uv run python scripts/run_stopping_fits_cp.py [variant ...] \
        > data/processed/stopping_fits_cp.log 2>&1 &

Variants (default: all three, nested):
    cp_none           no post-change-point parameters (the bound ignores the change point)
    cp_plateau        separate post-change-point plateau (bound_scale_post) in blocks 3, 4
    cp_plateau_slope  as cp_plateau plus an extra post-change-point slope of log theta (slope_post)
"""

import sys
import time
from pathlib import Path

import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
BLOCKS = [1, 2, 3, 4]
VARIANTS = {
    "cp_none": {},
    "cp_plateau": {"post_params": ("bound_scale",)},
    "cp_plateau_slope": {"post_params": ("bound_scale", "slope")},
}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main(variants):
    d = get_stopping_model_trials("MXSC", BLOCKS)
    n_blocks = d.groupby("subject_index")["block_index"].nunique()
    l_complete = d["subject_index"].isin(n_blocks.index[n_blocks == len(BLOCKS)])
    log(f"{l_complete.groupby(d['subject_index']).first().sum()} subjects with all {len(BLOCKS)} blocks; "
        f"{(~l_complete.groupby(d['subject_index']).first()).sum()} subjects without them not fit")
    d = d[l_complete]
    for variant in variants:
        t0 = time.time()
        f = fit_stopping_models(d, group_col="condition", **VARIANTS[variant]).assign(task="MXSC", variant=variant)
        n_bad = int((~f.groupby("subject_index").success.first()).sum())
        log(f"{variant}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
            f"{n_bad} did not converge")
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        f.to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(VARIANTS))
