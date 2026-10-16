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
and a post-change-point plateau in blocks 3 and 4. Stage 2 (this script)
holds the shape, CV, rates, sensory noise and NDT fixed and frees, in every
block, the pre-change plateau, the post-change plateau and a pre-change tilt
of log theta, ``slope_pre * (j - change_point)`` at steps j before the
change point (pigeon.stopping, ``pre_slope_anchor='change_point'``; slopes
unpenalized). ``bound_scale`` is then the pre-change bound at the change
point, and the step is

    step = bound_scale_post / bound_scale     (B3 vs. B1, B4 vs. B2).

Fixed-block trials have no change point, so they get the change point of
the same subject's matched block (B1 from B3, B2 from B4) as a pseudo change
point; the SNR change itself never enters the likelihood (it uses the
on-screen positions), so a pseudo change point only sets the window and the
step time.

Writes data/processed/stopping_fits_cp_matched.pkl (one row per subject x
block), for Figure06_cpSummary. Run from the project root (about a minute):

    PYTHONPATH=. uv run python scripts/run_stopping_fits_cp_matched.py > data/processed/stopping_fits_cp_matched.log 2>&1
"""

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


def frozen_params(base_rows):
    """fit_stopping_model ``fixed`` dict from one subject's stage-1 rows (groups and shapes in sorted order)."""
    g = base_rows.groupby("group").first().sort_index()
    shapes = base_rows.groupby("time_course_group").first().sort_index()
    fixed = {name: g[name].to_numpy(float) for name in FROZEN}
    fixed["sensory_std"] = float(g["sensory_std"].iloc[0])
    fixed["ndt_probs"] = g[[f"ndt_p{v}" for v in NDT_VALUES]].iloc[0].to_numpy(float)
    fixed.update({name: shapes[name].to_numpy(float) for name in KNEE_PARAMS})
    return fixed


def main():
    d = get_stopping_model_trials("MXSC", BLOCKS)
    n_blocks = d.groupby("subject_index")["block_index"].nunique()
    d = d[d["subject_index"].isin(n_blocks.index[n_blocks == len(BLOCKS)])].copy()
    d["pair"] = np.where(d["block_index"].isin([1, 3]), "low", "high")
    base = pd.read_pickle(OUT_DIR / f"stopping_fits_{BASE}.pkl")
    missing = set(d["subject_index"]) - set(base["subject_index"])
    if missing:
        raise ValueError(f"subjects without a {BASE} fit: {sorted(missing)}")
    d = add_pseudo_change_points(d)
    subject_kwargs = {s: {"fixed": frozen_params(rows)} for s, rows in base.groupby("subject_index")}
    t0 = time.time()
    f = fit_stopping_models(d, group_col="condition", time_course_col="pair", subject_kwargs=subject_kwargs,
                            post_params=("bound_scale", "pre_slope"), pre_slope_anchor="change_point",
                            smooth_penalty=0.0).assign(task="MXSC", variant="cp_matched")
    n_bad = int((~f.groupby("subject_index").success.first()).sum())
    log(f"cp_matched: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; {n_bad} did not converge")
    out = OUT_DIR / "stopping_fits_cp_matched.pkl"
    f.to_pickle(out)
    log(f"wrote {out}")


if __name__ == "__main__":
    main()
