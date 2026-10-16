"""Anticipation and step at the change point, each as a difference between matched blocks (MXSC).

Subjects collapse their bounds within a trial whether or not a change point is
coming, so an absolute pre-change slope mostly measures that collapse. This
script measures the same slope, over the same pre-change-point window, in a
change-point block and in its matched fixed block (same starting SNR), and
takes the difference per subject:

    LowHigh anticipation = slope_pre(B3) - slope_pre(B1)
    HighLow anticipation = slope_pre(B4) - slope_pre(B2)

Two stages. Stage 1 is the cp_plateau_pair fit (run_stopping_fits_cp.py):
one knee-form time course per block pair, per-block plateau, CV and rates,
and a post-change-point plateau in blocks 3 and 4. Stage 2 holds all of that
fixed and frees, per block, the pre-window plateau (``bound_scale``) and a
tilt ``slope_pre * (j - 1)`` in log theta at steps j before the window end
(pigeon.stopping ``pre_slope_anchor='start'``, so ``bound_scale`` is the
bound at step 1; each subject has one change point per block, so this is a
reparameterization of the change-point anchor, not a different model). The
window ends at the change point in blocks 3 and 4. Fixed-block trials have
none, so they get the change point of the same subject's matched block
(B1 from B3, B2 from B4) as a pseudo change point; from it on, the fixed
block's bound returns to its stage-1 value, just as the change-point block's
returns to its stage-1 post-change plateau. The SNR change itself never
enters the likelihood (it uses the on-screen positions), so a pseudo change
point only sets the window. Slopes are unpenalized (smooth_penalty 0).

Variants (default: both):
    cp_tilt     as above: per block ``bound_scale`` and ``slope_pre``, post plateaus frozen
    cp_matched  also frees ``bound_scale_post`` in every block, so the fixed blocks get a step at the
                pseudo change point to compare with the real one:
                    step = bound_scale_post / bound_scale (B3 vs B1, B4 vs B2).
                Uses the change-point anchor (``slope_pre * (j - change_point)``), so ``bound_scale``
                is the pre-change bound at the change point and the ratio is the jump there
                beyond the pre-change tilt; the slopes are the same as with the start anchor.

Writes data/processed/stopping_fits_<variant>.pkl (one row per subject x
block). Run from the project root (each variant takes about a minute):

    PYTHONPATH=. uv run python scripts/run_stopping_fits_cp_tilt.py [variant ...] \
        > data/processed/stopping_fits_cp_tilt.log 2>&1
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import KNEE_PARAMS, NDT_VALUES, fit_stopping_models, get_stopping_model_trials

OUT_DIR = Path("data/processed")
BLOCKS = [1, 2, 3, 4]
BASE = "cp_plateau_pair"
MATCHED_CP_BLOCK = {1: 3, 2: 4}   # fixed block -> change-point block with the same starting SNR
FROZEN = ("bound_cv", "guess_rate", "lapse_rate", "anticipation_rate")
VARIANTS = {"cp_tilt": {"free_post": False, "pre_slope_anchor": "start"},
            "cp_matched": {"free_post": True, "pre_slope_anchor": "change_point"}}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def add_pseudo_change_points(data_table):
    """Copy of the trials with each fixed-block trial given its subject's change point in the matched block."""
    d = data_table.copy()
    cps = d[d["block_index"].isin(MATCHED_CP_BLOCK.values())].groupby(["subject_index", "block_index"]).change_point
    if (cps.nunique() != 1).any():
        raise ValueError("expected one change point per subject and change-point block.")
    cps = cps.first()
    for fixed_block, cp_block in MATCHED_CP_BLOCK.items():
        lf = d["block_index"] == fixed_block
        d.loc[lf, "change_point"] = d.loc[lf, "subject_index"].map(cps.xs(cp_block, level="block_index")).to_numpy()
    return d


def frozen_params(base_rows, free_post=False):
    """
    fit_stopping_model ``fixed`` dict from one subject's stage-1 rows (groups and shapes in sorted order).

    With ``free_post``, ``bound_scale_post`` is left free (not in the dict).
    """
    g = base_rows.groupby("group").first().sort_index()
    shapes = base_rows.groupby("time_course_group").first().sort_index()
    fixed = {name: g[name].to_numpy(float) for name in FROZEN}
    # Fixed blocks have no post plateau in stage 1; after the pseudo change point they keep their own plateau.
    if not free_post:
        fixed["bound_scale_post"] = g["bound_scale_post"].fillna(g["bound_scale"]).to_numpy(float)
    fixed["sensory_std"] = float(g["sensory_std"].iloc[0])
    fixed["ndt_probs"] = g[[f"ndt_p{v}" for v in NDT_VALUES]].iloc[0].to_numpy(float)
    fixed.update({name: shapes[name].to_numpy(float) for name in KNEE_PARAMS})
    return fixed


def main(variants):
    d = get_stopping_model_trials("MXSC", BLOCKS)
    n_blocks = d.groupby("subject_index")["block_index"].nunique()
    d = d[d["subject_index"].isin(n_blocks.index[n_blocks == len(BLOCKS)])].copy()
    d["pair"] = np.where(d["block_index"].isin([1, 3]), "low", "high")
    base = pd.read_pickle(OUT_DIR / f"stopping_fits_{BASE}.pkl")
    missing = set(d["subject_index"]) - set(base["subject_index"])
    if missing:
        raise ValueError(f"subjects without a {BASE} fit: {sorted(missing)}")
    d = add_pseudo_change_points(d)
    for variant in variants:
        cfg = VARIANTS[variant]
        subject_kwargs = {s: {"fixed": frozen_params(rows, cfg["free_post"])} for s, rows in base.groupby("subject_index")}
        t0 = time.time()
        f = fit_stopping_models(d, group_col="condition", time_course_col="pair", subject_kwargs=subject_kwargs,
                                post_params=("bound_scale", "pre_slope"), pre_slope_anchor=cfg["pre_slope_anchor"],
                                smooth_penalty=0.0).assign(task="MXSC", variant=variant)
        n_bad = int((~f.groupby("subject_index").success.first()).sum())
        log(f"{variant}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
            f"{n_bad} did not converge")
        out = OUT_DIR / f"stopping_fits_{variant}.pkl"
        f.to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(VARIANTS))
