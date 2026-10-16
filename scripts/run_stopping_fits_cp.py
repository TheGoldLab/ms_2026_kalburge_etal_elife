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

Variants (default: the first three, nested):
    cp_none           no post-change-point parameters (the bound ignores the change point)
    cp_plateau        separate post-change-point plateau (bound_scale_post) in blocks 3, 4
    cp_plateau_slope  as cp_plateau plus an extra post-change-point slope of log theta (slope_post)
    cp_pre            anticipatory pre-change-point slope of log theta (slope_pre), anchored at the change point
    cp_plateau_pre    cp_plateau plus slope_pre: the step at the change point with anticipation fit jointly
    cp_plateau_pair, cp_plateau_pre_pair
                      as cp_plateau / cp_plateau_pre but one time-course shape per block pair
                      (column 'pair': blocks 1 + 3 start at low SNR, 2 + 4 at high SNR), so each
                      change-point block's step and slope are measured against its matched fixed
                      block's shape rather than one shared by all four blocks

Fits run from several starting knees (pigeon.stopping.KNEE_STARTS) and keep the
best, except cp_plateau_pre: its single-start fit already took ~7.6 h, so it
starts each subject once, at the knee of that subject's cp_plateau fit (run
cp_plateau first). The knee is set mainly by the fixed blocks, which slope_pre
doesn't touch.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
BLOCKS = [1, 2, 3, 4]
VARIANTS = {
    "cp_none": {},
    "cp_plateau": {"post_params": ("bound_scale",)},
    "cp_plateau_slope": {"post_params": ("bound_scale", "slope")},
    "cp_pre": {"post_params": ("pre_slope",)},
    "cp_plateau_pre": {"post_params": ("bound_scale", "pre_slope"), "knee_from": "cp_plateau"},
    "cp_plateau_pair": {"post_params": ("bound_scale",), "time_course_col": "pair"},
    "cp_plateau_pre_pair": {"post_params": ("bound_scale", "pre_slope"), "time_course_col": "pair"},
}
DEFAULT_VARIANTS = ["cp_none", "cp_plateau", "cp_plateau_slope"]


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main(variants):
    d = get_stopping_model_trials("MXSC", BLOCKS)
    n_blocks = d.groupby("subject_index")["block_index"].nunique()
    l_complete = d["subject_index"].isin(n_blocks.index[n_blocks == len(BLOCKS)])
    log(f"{l_complete.groupby(d['subject_index']).first().sum()} subjects with all {len(BLOCKS)} blocks; "
        f"{(~l_complete.groupby(d['subject_index']).first()).sum()} subjects without them not fit")
    d = d[l_complete].copy()
    # Blocks 1 (fixed low) and 3 (LowHigh) start at low SNR; 2 (fixed high) and 4 (HighLow) at high SNR.
    d["pair"] = np.where(d["block_index"].isin([1, 3]), "low", "high")
    for variant in variants:
        t0 = time.time()
        kwargs = dict(VARIANTS[variant])
        subject_kwargs = None
        if "knee_from" in kwargs:
            knees = pd.read_pickle(OUT_DIR / f"stopping_fits_{kwargs.pop('knee_from')}.pkl").groupby("subject_index").knee.first()
            subject_kwargs = {s: {"knee_starts": (float(k),)} for s, k in knees.items()}
        f = fit_stopping_models(d, group_col="condition", subject_kwargs=subject_kwargs, **kwargs).assign(
            task="MXSC", variant=variant)
        n_bad = int((~f.groupby("subject_index").success.first()).sum())
        log(f"{variant}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
            f"{n_bad} did not converge")
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        f.to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_VARIANTS)
