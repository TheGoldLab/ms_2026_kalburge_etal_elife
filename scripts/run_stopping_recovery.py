"""Parameter recovery and mechanism attribution for the stopping model (pigeon.stopping).

Simulates subjects at MXSC fixed-block trial counts (Low 71, High 118 trials;
step SD 0.05, step means 0.01 / 0.03) and fits each with fit_stopping_model's
defaults. Scenarios:

    random         all mechanisms on, parameters drawn over plausible ranges,
                   time course a random log-linear collapse or increase
    guess_only     guesses, flat bound, no sensory noise
    noise_only     sensory noise, flat bound, no guesses
    collapse_only  collapsing bound, no guesses, no sensory noise

Writes data/processed/stopping_recovery.pkl for notebooks/Test_stoppingModel.ipynb.
Run from the project root:

    nohup uv run python scripts/run_stopping_recovery.py > data/processed/stopping_recovery.log 2>&1 &
"""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import KNOTS, fit_stopping_model, simulate_stopping_trials

OUT = Path("data/processed/stopping_recovery.pkl")
BLOCKS = {1: (71, 0.01), 2: (118, 0.03)}   # block: (trials, step mean)
STEP_STD = 0.05
N_RANDOM, N_PER_MECHANISM = 40, 12


def make_subject(seed, scenario):
    """Simulated two-block subject and its true parameters."""
    rng = np.random.default_rng(seed)
    t = dict(bound_cv=rng.uniform(0.15, 0.6), guess_rate=rng.uniform(0.005, 0.06),
             lapse_rate=rng.uniform(0.0, 0.08), anticipation_rate=rng.uniform(0.0, 0.05),
             sensory_std=rng.uniform(0.0, 0.05))
    ramp = (np.array(KNOTS) - 1) / (KNOTS[-1] - 1)
    log_h = rng.uniform(-0.9, 0.5) * ramp
    if scenario == "guess_only":
        t.update(sensory_std=0.0, guess_rate=rng.uniform(0.04, 0.1))
        log_h = 0 * ramp
    elif scenario == "noise_only":
        t.update(guess_rate=0.0, sensory_std=rng.uniform(0.03, 0.06))
        log_h = 0 * ramp
    elif scenario == "collapse_only":
        t.update(guess_rate=0.0, sensory_std=0.0)
        log_h = rng.uniform(-1.0, -0.5) * ramp
    scale1 = rng.uniform(0.12, 0.35)
    scale2 = scale1 * rng.uniform(0.6, 1.1)
    p1 = rng.uniform(0.4, 0.95)
    d = pd.concat([
        simulate_stopping_trials(n, gm, STEP_STD, s, ndt_probs=(p1, 1 - p1), log_h=log_h, rng=rng, **t)
        .assign(block_index=b)
        for (b, (n, gm)), s in zip(BLOCKS.items(), (scale1, scale2))], ignore_index=True)
    return d, dict(**t, scale1=scale1, scale2=scale2, ndt_p1=p1, log_h6=log_h[2], log_h16=log_h[-1])


def job(args):
    seed, scenario = args
    d, truth = make_subject(seed, scenario)
    t0 = time.time()
    r = fit_stopping_model(d)
    p = r["params"].set_index("group")
    fit = dict(bound_cv=p.bound_cv.mean(), guess_rate=p.guess_rate.mean(), lapse_rate=p.lapse_rate.mean(),
               anticipation_rate=p.anticipation_rate.mean(), sensory_std=p.sensory_std.iloc[0],
               scale1=p.loc[1, "bound_scale"], scale2=p.loc[2, "bound_scale"], ndt_p1=p.ndt_p1.iloc[0],
               log_h6=p.log_h_k6.iloc[0], log_h16=p.log_h_k16.iloc[0])
    return dict(seed=seed, scenario=scenario, secs=time.time() - t0, converged=r["success"],
                **{f"true_{k}": v for k, v in truth.items()}, **{f"fit_{k}": v for k, v in fit.items()})


if __name__ == "__main__":
    jobs = ([(s, "random") for s in range(N_RANDOM)]
            + [(100 + 20 * i + s, sc) for i, sc in enumerate(("guess_only", "noise_only", "collapse_only"))
               for s in range(N_PER_MECHANISM)])
    t0 = time.time()
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(job, jobs))
    pd.DataFrame(rows).to_pickle(OUT)
    print(f"{len(rows)} fits in {(time.time() - t0) / 60:.1f} min; wrote {OUT}", flush=True)
