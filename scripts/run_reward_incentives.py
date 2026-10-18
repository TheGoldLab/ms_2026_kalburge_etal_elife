"""Reward-rate moments of bound policies for an ideal participant (Figure 8).

Simulates, with pigeon.incentives.get_reward_moments (no sensory noise, bound
variability, guesses or lapses), the per-trial coin and step moments that give
each policy's reward rate and how well one block of it can be told from the
best policy's:

- penalty: flat bounds BOUNDS in the online task (step SD 0.15) at each SNR
  (step means 0.05 and 0.15), scored with each penalty rule (BLOCK_DEFAULTS
  1-3: none, 4 coins, 30 steps), with each cohort's NDT distribution (mean
  fitted P(NDT = 1) in stopping_fits_main.pkl: OL blocked, MX mixed SNR).
  Mixed-SNR blocks are the half-and-half mixture of the two SNRs' moments
  (done in the notebook).
- change_point: the change-point blocks (MXSC; step SD 0.05, step mean 0.01 ->
  0.03 or 0.03 -> 0.01, +/-1 coin), at every change-point time a subject had.
  Policies: a pre-change flat bound b (BOUNDS_CP) with the post-change bound
  b * ratio (RATIOS), or with the post-change bound b and the pre-change bound
  tilted, b * exp(slope * (j - cp / 2)) (SLOPES; the mean pre-change log bound
  is kept, as in run_cp_incentive_sims.py). NDT: mean fitted P(NDT = 1) in
  stopping_fits_cp_plateau_pair.pkl.

Writes data/processed/reward_incentives.pkl. Run from the project root
(about 25 minutes on 18 cores):

    PYTHONPATH=. uv run python scripts/run_reward_incentives.py > data/processed/reward_incentives.log 2>&1
"""

import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.incentives import get_reward_moments
from pigeon.simulation import BLOCK_DEFAULTS
from pigeon.stopping import get_stopping_model_trials

OUT = Path("data/processed/reward_incentives.pkl")
SEED = 20261018

# Online task (cohorts 1 and 2)
STEP_STD = 0.15
SNR_MEANS = {"low": 0.05, "high": 0.15}
BOUNDS = np.round(np.arange(0.01, 0.82, 0.01), 2)  # to Figure 8's axis edge
PENALTY_RULES = [BLOCK_DEFAULTS[b] for b in (1, 2, 3)]
NUM_TRIALS = 500_000

# Change-point task (cohort 3): condition -> (block, pre-change mean, post-change mean)
CP_STEP_STD = 0.05
CP_DESIGNS = {"LowHigh": (3, 0.01, 0.03), "HighLow": (4, 0.03, 0.01)}
CP_RULES = [{"coins_gained": 1, "coins_lost": 1, "steps_lost": 0}]
CP_STEPS_PER_BLOCK = 1000
BOUNDS_CP = np.round(np.arange(0.01, 0.51, 0.01), 2)
RATIOS = np.exp(np.linspace(np.log(0.1), np.log(10.0), 41))
SLOPES = np.round(np.linspace(-0.6, 0.6, 49), 3)
NUM_TRIALS_CP = 200_000
MAX_STEPS = 50


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def _penalty(args):
    task, snr, ndt_probs, seed = args
    m = get_reward_moments(
        SNR_MEANS[snr], BOUNDS, STEP_STD, ndt_probs, PENALTY_RULES, NUM_TRIALS, MAX_STEPS, np.random.default_rng(seed)
    )
    return (task, snr), m


def _change_point(args):
    cond, cp, ndt_probs, seed = args
    _, pre, post = CP_DESIGNS[cond]
    j = np.arange(1, MAX_STEPS)  # positions 1..MAX_STEPS - 1
    means = np.where(j < cp, pre, post)  # the step producing position cp is the first post-change step
    pre_pos = j < cp
    step = [np.where(pre_pos, b, b * r) for b in BOUNDS_CP for r in RATIOS]
    slope = [np.where(pre_pos, b * np.exp(s * (j - cp / 2)), b) for b in BOUNDS_CP for s in SLOPES]
    m = get_reward_moments(
        means,
        np.array(step + slope),
        CP_STEP_STD,
        ndt_probs,
        CP_RULES,
        NUM_TRIALS_CP,
        MAX_STEPS,
        np.random.default_rng(seed),
    )[0]
    n_step = len(step)
    return (cond, cp), (
        m[:n_step].reshape(len(BOUNDS_CP), len(RATIOS), 5),
        m[n_step:].reshape(len(BOUNDS_CP), len(SLOPES), 5),
    )


def _ndt_probs(fits):
    p1 = float(fits.groupby("subject_index").ndt_p1.first().mean())
    return (p1, 1 - p1)


def main():
    main_fits = pd.read_pickle("data/processed/stopping_fits_main.pkl")
    ndt = {task: _ndt_probs(main_fits[main_fits.task == task]) for task in ("OL", "MX")}
    ndt["MXSC"] = _ndt_probs(pd.read_pickle("data/processed/stopping_fits_cp_plateau_pair.pkl"))
    log(f"P(NDT = 1, 2): {ndt}")
    trials = get_stopping_model_trials("MXSC", [3, 4], verbose=False)
    change_points = trials.groupby(["block_index", "subject_index"]).change_point.first()

    penalty_jobs = [
        (task, snr, ndt[task], SEED + k)
        for k, (task, snr) in enumerate((t, s) for t in ("OL", "MX") for s in SNR_MEANS)
    ]
    cp_jobs = [
        (cond, int(cp), ndt["MXSC"], SEED + 1000 * blk + int(cp))
        for cond, (blk, _, _) in CP_DESIGNS.items()
        for cp in sorted(change_points.loc[blk].unique())
    ]
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        penalty = dict(ex.map(_penalty, penalty_jobs))
        log(f"penalty blocks: {len(penalty_jobs)} jobs ({(time.time() - t0) / 60:.1f} min)")
        change_point = dict(ex.map(_change_point, cp_jobs))
        log(f"change-point blocks: {len(cp_jobs)} (condition, change point) jobs ({(time.time() - t0) / 60:.1f} min)")
    out = {
        "penalty": penalty,
        "bounds": BOUNDS,
        "steps_per_block": BLOCK_DEFAULTS[1]["steps_per_block"],
        "change_point": change_point,
        "change_points": change_points,
        "cp_designs": CP_DESIGNS,
        "bounds_cp": BOUNDS_CP,
        "ratios": RATIOS,
        "slopes": SLOPES,
        "cp_steps_per_block": CP_STEPS_PER_BLOCK,
        "ndt_probs": ndt,
    }
    with open(OUT, "wb") as f:
        pickle.dump(out, f)
    log(f"wrote {OUT}")


if __name__ == "__main__":
    main()
