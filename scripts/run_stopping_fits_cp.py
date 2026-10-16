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

Variants (default: cp_plateau_pair):
    cp_plateau_pair   post-change-point plateau (bound_scale_post) in blocks 3 and 4, and one
                      time-course shape per block pair (column 'pair': blocks 1 + 3 start at low
                      SNR, 2 + 4 at high SNR), so each change-point block is measured against its
                      matched fixed block's shape. Stage 1 of Figure 6
                      (scripts/run_stopping_fits_cp_matched.py is stage 2); about 3 h.
    cp_none           no post-change-point parameters and one shape for all four blocks (the
                      bound ignores the change point); a baseline for model comparison.

Fits run from several starting knees (pigeon.stopping.KNEE_STARTS) and keep the best.
"""

import sys
import time
from pathlib import Path

import numpy as np

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
BLOCKS = [1, 2, 3, 4]
VARIANTS = {
    "cp_plateau_pair": {"post_params": ("bound_scale",), "time_course_col": "pair"},
    "cp_none": {},
}


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
        f = fit_stopping_models(d, group_col="condition", **VARIANTS[variant]).assign(task="MXSC", variant=variant)
        n_bad = int((~f.groupby("subject_index").success.first()).sum())
        log(f"{variant}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
            f"{n_bad} did not converge")
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        f.to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["cp_plateau_pair"])
