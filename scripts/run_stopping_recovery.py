"""Parameter recovery for the stopping model (pigeon.stopping) at OL and MX trial counts.

Simulates subjects with each block's median real trial count (after the
get_stopping_model_trials exclusions) and step statistics, then fits each with
fit_stopping_model's defaults (bound scale and CV, guess, lapse and
anticipation rates per block; time course, sensory noise and NDT shared):

    OL  blocks 1-6: 111, 64, 33, 150, 121, 78 trials; step SD 0.15, step mean
        0.05 (blocks 1-3) or 0.15 (blocks 4-6)
    MX  blocks 1-3: 114, 92, 47 trials; step SD 0.15, step mean 0.05 or 0.15
        mixed 50/50 within each block

True parameters are drawn over plausible ranges: per block for the bound
scale and CV and the three rates; per subject for sensory noise, NDT and the
time course (a random log-linear collapse or increase through the knots).

Writes data/processed/stopping_recovery.pkl (one row per subject x block) for
notebooks/Test_stoppingModel.ipynb. Run from the project root:

    nohup uv run python scripts/run_stopping_recovery.py > data/processed/stopping_recovery.log 2>&1 &
"""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import ANCHOR, KNOTS, fit_stopping_model, simulate_stopping_trials

OUT = Path("data/processed/stopping_recovery.pkl")
STEP_STD = 0.15
DESIGNS = {   # block: (trials, step means (mixed 50/50 if two))
    "OL": {1: (111, (0.05,)), 2: (64, (0.05,)), 3: (33, (0.05,)),
           4: (150, (0.15,)), 5: (121, (0.15,)), 6: (78, (0.15,))},
    "MX": {1: (114, (0.05, 0.15)), 2: (92, (0.05, 0.15)), 3: (47, (0.05, 0.15))},
}
N_SUBJECTS = {"OL": 32, "MX": 16}
PER_BLOCK = ("bound_scale", "bound_cv", "guess_rate", "lapse_rate", "anticipation_rate")


def make_subject(task, seed):
    """Simulated subject (all blocks) and its true parameters."""
    rng = np.random.default_rng(seed)
    sensory_std = rng.uniform(0.0, 0.12)
    p1 = rng.uniform(0.4, 0.95)
    ramp = (np.array(KNOTS) - ANCHOR) / (KNOTS[-1] - KNOTS[0])   # 0 at the anchor
    log_h = rng.uniform(-0.8, 0.4) * ramp
    shared = dict(sensory_std=sensory_std, log_h_first=log_h[0], log_h_last=log_h[-1])
    parts, truth = [], {}
    for block, (n, means) in DESIGNS[task].items():
        b = dict(bound_scale=rng.uniform(0.15, 0.6), bound_cv=rng.uniform(0.15, 0.6),
                 guess_rate=rng.uniform(0.005, 0.06), lapse_rate=rng.uniform(0.0, 0.08),
                 anticipation_rate=rng.uniform(0.0, 0.1))
        sizes = np.diff(np.round(np.linspace(0, n, len(means) + 1)).astype(int))
        for m, k in zip(means, sizes):
            d = simulate_stopping_trials(k, m, STEP_STD, log_h=log_h, ndt_probs=(p1, 1 - p1), rng=rng,
                                         sensory_std=sensory_std, **b)
            d["snr"] = m / STEP_STD
            parts.append(d.assign(block_index=block))
        truth[block] = b
    return pd.concat(parts, ignore_index=True), shared, p1, truth


def job(args):
    task, seed = args
    d, shared, p1, truth = make_subject(task, seed)
    t0 = time.time()
    r = fit_stopping_model(d)
    secs = time.time() - t0
    p = r["params"].set_index("group")
    rows = []
    for block, tb in truth.items():
        fb = p.loc[block]
        rows.append(dict(
            task=task, seed=seed, block=block, n_trials=int(fb.n_trials), secs=secs, converged=r["success"],
            **{f"true_{k}": v for k, v in tb.items()}, **{f"true_{k}": v for k, v in shared.items()},
            true_ndt_p1=p1,
            **{f"fit_{k}": fb[k] for k in PER_BLOCK}, fit_sensory_std=fb.sensory_std,
            fit_log_h_first=fb[f"log_h_k{KNOTS[0]}"], fit_log_h_last=fb[f"log_h_k{KNOTS[-1]}"],
            fit_ndt_p1=fb.ndt_p1))
    return rows


if __name__ == "__main__":
    jobs = [(task, 1000 * ti + s) for ti, task in enumerate(DESIGNS) for s in range(N_SUBJECTS[task])]
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor() as pool:
        for i, r in enumerate(pool.map(job, jobs)):
            rows += r
            print(f"{i + 1}/{len(jobs)} {r[0]['task']} {r[0]['secs']:.0f}s", flush=True)
    pd.DataFrame(rows).to_pickle(OUT)
    print(f"done: {len(jobs)} fits in {(time.time() - t0) / 60:.1f} min; wrote {OUT}", flush=True)
