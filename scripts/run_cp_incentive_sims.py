"""Reward-rate incentives for adjusting the bound around a change point (MXSC), per subject.

For each subject and change-point block (B3 LowHigh, B4 HighLow), simulates the
subject's own fitted stopping model (stage 1 of the matched-block analysis:
cp_plateau_pair, the block's plateau, CV, rates and its pair's knee time
course) at the subject's change point, under two manipulations:

- step: the post-change plateau set to ``ratio`` x the pre-change plateau
  (``RATIOS``); reward rate relative to ratio 1 is the incentive for a step at
  the change point (Figure 6 E, F).
- slope: an anticipatory tilt of log theta before the change point,
  ``slope * (j - cp / 2)``, which keeps the mean pre-change log bound
  (``SLOPES``), with the post-change plateau unchanged. Each subject has one
  change point per block, so this is pigeon.stopping's change-point-anchored
  ``slope_pre`` with the plateau scaled by ``exp(slope * cp / 2)``. Each slope is
  also simulated without the SNR change ('base'), so the change-specific
  incentive, (RR_cp(s) - RR_cp(0)) - (RR_base(s) - RR_base(0)), removes the
  part of the gain that any tilt would bring in a fixed block (Figure 6 A, B).

Reward rate is the task's: +1 coin correct, -1 error, per 1000 steps
(``1000 * mean(+/-1) / mean(RT)``). All simulations of a subject and block share
one seed, so the curves are smooth in the manipulated parameter.

Writes data/processed/cp_incentive_step.pkl and cp_incentive_slope.pkl. Run from
the project root (several minutes):

    PYTHONPATH=. uv run python scripts/run_cp_incentive_sims.py > data/processed/cp_incentive_sims.log 2>&1
"""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import KNEE_PARAMS, get_stopping_model_trials, simulate_stopping_trials

OUT_DIR = Path("data/processed")
BASE = "cp_plateau_pair"
# condition: (group, block, pre-change generative mean, post-change generative mean, slope grid)
DESIGNS = {
    "LowHigh": ("B3", 3, 0.01, 0.03, np.round(np.linspace(-0.1, 0.6, 29), 4)),
    "HighLow": ("B4", 4, 0.03, 0.01, np.round(np.linspace(-0.6, 0.1, 29), 4)),
}
RATIOS = np.exp(np.linspace(np.log(0.1), np.log(10.0), 41))
NUM_TRIALS, STEP_STD, MAX_STEPS = 40_000, 0.05, 50


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def _reward_rate(f, cp, pre_mean, post_mean, bound_scale, bound_scale_post, slope, seed):
    sim = simulate_stopping_trials(
        NUM_TRIALS,
        pre_mean,
        STEP_STD,
        bound_scale,
        f["bound_cv"],
        f["guess_rate"],
        f["lapse_rate"],
        f["anticipation_rate"],
        f["sensory_std"],
        knee_shape=tuple(f[c] for c in KNEE_PARAMS),
        ndt_probs=[f["ndt_p1"], f["ndt_p2"]],
        change_point=cp,
        generative_mean_post=post_mean,
        bound_scale_post=bound_scale_post,
        slope_pre=slope,
        max_steps=MAX_STEPS,
        rng=np.random.default_rng(seed),
    )
    return 1000 * np.where(sim["correct"].to_numpy() == 1, 1.0, -1.0).mean() / sim["RT"].mean()


def _one_subject(args):
    subj, cond, f, cp, seed = args
    _, _, pre, post, slopes = DESIGNS[cond]
    b = f["bound_scale"]
    step = [(subj, cond, r, _reward_rate(f, cp, pre, post, b, b * r, 0.0, seed)) for r in RATIOS]
    slope = [
        (subj, cond, kind, s, _reward_rate(f, cp, pre, pm, b * np.exp(s * cp / 2), b, s, seed))
        for kind, pm in (("cp", post), ("base", pre))
        for s in slopes
    ]
    return step, slope


def main():
    fits = pd.read_pickle(OUT_DIR / f"stopping_fits_{BASE}.pkl")
    d = get_stopping_model_trials("MXSC", [3, 4], verbose=False)
    cps = d.groupby(["subject_index", "block_index"]).change_point.agg(["first", "nunique"])
    if (cps["nunique"] != 1).any():
        raise ValueError("expected one change point per subject and change-point block.")
    jobs = []
    for cond, (grp, blk, *_) in DESIGNS.items():
        for _, f in fits[fits.group == grp].iterrows():
            key = (f["subject_index"], float(blk))
            if key in cps.index:
                jobs.append(
                    (f["subject_index"], cond, f, int(cps.loc[key, "first"]), int(f["subject_index"]) * 10 + blk)
                )
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(_one_subject, jobs))
    step = pd.DataFrame([r for s, _ in res for r in s], columns=["subject_index", "condition", "ratio", "rr"])
    slope = pd.DataFrame([r for _, s in res for r in s], columns=["subject_index", "condition", "kind", "slope", "rr"])
    log(f"{len(jobs)} subject x block simulations in {(time.time() - t0) / 60:.1f} min")
    for name, t in (("step", step), ("slope", slope)):
        out = OUT_DIR / f"cp_incentive_{name}.pkl"
        t.to_pickle(out)
        log(f"wrote {out}")


if __name__ == "__main__":
    main()
