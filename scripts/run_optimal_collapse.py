"""
Optimal vs. best flat bound in mixed-SNR blocks with zero-SNR trials mixed in (Figure05S03).

For each penalty condition of the mixed-SNR task (BLOCK_DEFAULTS 1-3: no penalty, 4 coins,
30 steps) and each share of zero-SNR trials (the rest split evenly between step means 0.05
and 0.15, SD 0.15), solves the reward-rate-optimal bound over the trial by dynamic
programming (pigeon.ideal_observer.get_optimal_bounds_mixture) and finds the best flat
bound (get_best_flat_bound). Steps charged per trial besides the decision: 1 (trial start)
plus cohort 2's mean non-decision time (1 or 2 steps, mean fitted P(NDT = 1) from
stopping_fits_main.pkl).

Writes data/processed/optimal_collapse.pkl: one row per condition x zero-SNR share with the
optimal and best-flat reward rates (coins per step), the best flat bound and the optimal
bound at every step.

    uv run python scripts/run_optimal_collapse.py [n_workers]
"""

import sys
import time
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from pigeon.ideal_observer import get_best_flat_bound, get_optimal_bounds_mixture
from pigeon.pathDefaults import DATA_DIR

STEP_MEANS = [0.0, 0.05, 0.15]
ZERO_SHARES = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 1 / 3]
CONDITIONS = {1: {"loss": 0, "error_cost": 0}, 2: {"loss": 4, "error_cost": 0}, 3: {"loss": 0, "error_cost": 30}}


def _start_cost():
    mx = pd.read_pickle(DATA_DIR / "stopping_fits_main.pkl").query("task == 'MX'")
    p1 = float(mx.groupby("subject_index").ndt_p1.first().mean())
    return 1 + (1 * p1 + 2 * (1 - p1)), p1


def _run(args):
    block, share, start_cost = args
    weights = [share, (1 - share) / 2, (1 - share) / 2]
    kw = dict(gain=1, start_cost=start_cost, **CONDITIONS[block])
    rho, bound = get_optimal_bounds_mixture(STEP_MEANS, weights, **kw)
    b_flat, rho_flat = get_best_flat_bound(STEP_MEANS, weights, **kw)
    return {"block": block, "zero_share": share, "rho_opt": rho, "rho_flat": rho_flat, "b_flat": b_flat, "bound": bound}


if __name__ == "__main__":
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    start_cost, p1 = _start_cost()
    print(f"P(NDT = 1) = {p1:.3f}; steps charged per trial besides the decision = {start_cost:.3f}")
    t0 = time.time()
    jobs = [(b, s, start_cost) for b in CONDITIONS for s in ZERO_SHARES]
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        df = pd.DataFrame(list(pool.map(_run, jobs)))
    df["start_cost"] = start_cost
    df["gain_pct"] = 100 * (df.rho_opt / df.rho_flat - 1)
    df.to_pickle(DATA_DIR / "optimal_collapse.pkl")
    print(df.drop(columns="bound").round(4).to_string(index=False))
    print(f"saved {DATA_DIR / 'optimal_collapse.pkl'} ({time.time() - t0:.0f} s)")
