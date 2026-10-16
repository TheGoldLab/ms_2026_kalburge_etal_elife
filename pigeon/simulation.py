"""
Fixed-bound simulations of the task.
Python translations of getPigeon_simulatedData.m and getPigeon_simulatedDataTable.m.

Generative model
----------------
Each trial is a 1-D random walk starting at 0. At every step the position
increments by a sample from N(generative_mean, generative_std) (the sign of
the mean is the correct side, here always right). The walk stops at the first
step at which |position| reaches the trial's bound, and the response follows a
non-decision time (NDT) of whole steps later.

Uses
----
- ``simulate_trials`` (the walk itself): the bias calibration
  (notebooks/Make_biasCorrection.ipynb), 1,000,000 trials per run.
- ``get_simulated_data_table`` (whole blocks under the task's step budget and
  reward rules, measured like real data): the reward rate of fixed bounds in
  Figure02S01, Figure04, Figure04S01 and Figure05.

Constants
---------
MIN_BOUND : float
    Floor on a sampled bound (with bound_std > 0).
BLOCK_DEFAULTS, BLOCK_DEFAULTS_PD : dict
    Step budget and reward rules of each block of the online (OL/MX) and
    predefined-bound (PD) tasks.
"""

import os

import numpy as np
import pandas as pd

from .data import WALL, apply_bias_corrections, get_bounds

MIN_BOUND = 0.03  # minimum allowed bound (prevents degenerate zero-bound trials)

# Per-block reward rules (1-indexed block numbers, matching MATLAB blockDefaults): blocks 1-3 (and 4-6, the
# same conditions at high SNR) are no penalty, coin penalty (4 coins per error) and step penalty (30 steps per
# error); 600 steps per block.
BLOCK_DEFAULTS = {
    1: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 0, "steps_lost": 0},
    2: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 4, "steps_lost": 0},
    3: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 0, "steps_lost": 30},
    4: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 0, "steps_lost": 0},
    5: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 4, "steps_lost": 0},
    6: {"steps_per_block": 600, "coins_gained": 1, "coins_lost": 0, "steps_lost": 30},
}

# Same reward rules, but PD's step budget is 800/block (the raw PD CSVs' tc_steps_max field, constant across
# all subjects).
BLOCK_DEFAULTS_PD = {block: dict(rules, steps_per_block=800) for block, rules in BLOCK_DEFAULTS.items()}


def simulate_trials(
    generative_mean=0.05,
    generative_std=0.15,
    num_trials=1_000_000,
    max_steps=50,
    bound_mean=0.0,
    bound_std=0.0,
    ndt_min=1,
    ndt_max=1,
    ndt_probs=None,
    rng=None,
    return_steps=True,
):
    """
    Simulate fixed-bound trials (core engine).
    Translated from getPigeon_simulatedData.m.

    Parameters
    ----------
    generative_mean : float or array-like
        Mean step (positive: right is correct). Several values are randomly
        interleaved across trials (e.g. mixed SNR).
    generative_std : float
        SD of each step, shared by all generative means.
    num_trials : int
    max_steps : int
        Steps per trial; a trial that never reaches the bound ends here with no choice.
    bound_mean : float or array-like
        Bound. One value per generative mean gives each SNR level its own bound.
    bound_std : float
        Trial-to-trial SD of the bound (0 = fixed), floored at MIN_BOUND.
    ndt_min, ndt_max : int
        NDT (steps) drawn from {ndt_min, ..., ndt_max}, then limited so that
        RT <= max_steps. NDT 0 means the response comes on the step that
        reaches the bound (the predefined-bound task).
    ndt_probs : sequence of float or None
        Probability of each NDT value ndt_min..ndt_max; None = uniform.
    rng : np.random.Generator or None
    return_steps : bool
        Also return each trial's position sequence (skip for large calibration runs).

    Returns
    -------
    choices    : (num_trials,) float array -- 1 = right, 0 = left, NaN if the bound was never reached
    rts        : (num_trials,) int array   -- steps until the response, including the NDT
    DV         : (num_trials, max_steps + 1) cumulative positions (column 0 = 0)
    bounds_out : (num_trials,) float array -- the trial's bound (NaN if never reached)
    ndts       : (num_trials,) int array
    snrs       : (num_trials,) float array -- generative_mean / generative_std of the trial
    steps      : list of position arrays up to the response, or None
    """
    if rng is None:
        rng = np.random.default_rng()

    generative_mean = np.atleast_1d(np.asarray(generative_mean, dtype=float))
    n_means = len(generative_mean)

    # Assign each trial a generative mean (interleaved at random if several)
    if n_means > 1:
        i_means = rng.integers(0, n_means, size=num_trials)
        trial_means = generative_mean[i_means]
    else:
        i_means = np.zeros(num_trials, dtype=int)
        trial_means = np.full(num_trials, generative_mean[0])

    # Positions: start at 0, each step ~ N(trial_mean, generative_std)
    noise = rng.normal(trial_means[:, None], generative_std, size=(num_trials, max_steps))
    DV = np.concatenate([np.zeros((num_trials, 1)), np.cumsum(noise, axis=1)], axis=1)

    bound_mean = np.atleast_1d(np.asarray(bound_mean, dtype=float))
    bound_per_trial = (
        bound_mean[i_means] if len(bound_mean) == n_means and n_means > 1 else np.full(num_trials, bound_mean[0])
    )
    if bound_std > 0:
        bound_per_trial = np.maximum(MIN_BOUND, rng.normal(bound_per_trial, bound_std))

    if ndt_probs is None:
        ndts = rng.integers(ndt_min, ndt_max + 1, size=num_trials)
    else:
        ndts = rng.choice(np.arange(ndt_min, ndt_max + 1), size=num_trials, p=np.asarray(ndt_probs) / np.sum(ndt_probs))

    # First bound crossings, fully vectorized (no Python step loop).
    abs_DV = np.abs(DV[:, :max_steps])
    crossed_at = abs_DV >= bound_per_trial[:, None]
    any_crossed = crossed_at.any(axis=1)
    first_ss = np.argmax(crossed_at, axis=1)  # meaningful only where any_crossed

    choices = np.full(num_trials, np.nan)
    rts = np.full(num_trials, max_steps, dtype=int)
    bounds_out = np.full(num_trials, np.nan)

    normal = any_crossed & (first_ss > 0)
    if normal.any():
        rows = np.where(normal)[0]
        ss = first_ss[rows]
        # Limit the NDT so that RT = crossing + NDT + 1 <= max_steps.
        ndts[rows] = np.clip(ndts[rows], 0, max_steps - ss - 1)
        rts[rows] = ss + ndts[rows] + 1
        choices[rows] = (DV[rows, ss] > 0).astype(float)
        bounds_out[rows] = bound_per_trial[rows]

    # A crossing at step 0 needs a zero bound: random RT and choice.
    ss0 = any_crossed & (first_ss == 0)
    if ss0.any():
        n_ss0 = int(ss0.sum())
        rts[ss0] = rng.integers(1, 3, size=n_ss0)
        choices[ss0] = rng.integers(0, 2, size=n_ss0).astype(float)
        bounds_out[ss0] = bound_per_trial[ss0]

    steps = [DV[tt, : rts[tt]] for tt in range(num_trials)] if return_steps else None
    return choices, rts, DV, bounds_out, ndts, trial_means / generative_std, steps


def get_simulated_data_table(
    specs,
    generative_mean=0.05,
    generative_std=0.15,
    num_trials=600,
    max_steps=50,
    bound_mean=0.0,
    bound_std=0.0,
    ndt_min=1,
    ndt_max=1,
    ndt_probs=None,
    correct_bias=None,
    rng=None,
    block_defaults=BLOCK_DEFAULTS,
):
    """
    Simulate whole blocks of fixed-bound trials in the format of get_data_table().
    Translated from getPigeon_simulatedDataTable.m.

    Each simulated subject x block runs ``simulate_trials`` until the block's
    step budget is spent (an error also costs the block's ``steps_lost``; a
    trial cut off by the budget gets no choice), counts coins with the block's
    reward rules (``coin_count`` is the running total, as in the data), and
    measures bounds with ``get_bounds`` as for real data.

    Parameters
    ----------
    specs : dict
        'num_subjects' (int) and 'blocks' (int or list of block numbers in block_defaults).
    generative_mean, generative_std, max_steps, bound_mean, bound_std, ndt_min, ndt_max, ndt_probs
        Passed to simulate_trials (shared by all subjects and blocks). For
        mixed SNR with one bound per SNR, pass matching lists of
        generative_mean and bound_mean.
    num_trials : int
        Trials simulated per block before applying the step budget.
    correct_bias : str, Path or None
        Bias-correction file applied to the measured bounds (None = raw).
    rng : np.random.Generator or None
    block_defaults : dict
        Step budget and reward rules per block (BLOCK_DEFAULTS, or BLOCK_DEFAULTS_PD for the PD task).

    Returns
    -------
    pd.DataFrame with get_data_table's core columns (subject_index,
    block_index, trial_number, bound, abs_bound, RT, DT, choice, correct,
    coin_count, snr, steps, rt_cutoff, rt_below_cutoff, wall_hit).
    """
    if rng is None:
        rng = np.random.default_rng()
    blocks = np.atleast_1d(np.asarray(specs.get("blocks", [1]), dtype=int))
    subjects = np.arange(1, int(specs.get("num_subjects", 1)) + 1)

    dfs = []
    for subj in subjects:
        for block in blocks:
            rules = block_defaults[int(block)]
            choices, rts, _, _, _, snrs, steps = simulate_trials(
                generative_mean=generative_mean,
                generative_std=generative_std,
                num_trials=num_trials,
                max_steps=max_steps,
                bound_mean=bound_mean,
                bound_std=bound_std,
                ndt_min=ndt_min,
                ndt_max=ndt_max,
                ndt_probs=ndt_probs,
                rng=rng,
            )

            # Cumulative steps and coins; stop when the step budget is reached
            step_counts = np.cumsum(rts + rules["steps_lost"] * (choices == 0))
            coin_counts = np.cumsum(-rules["coins_lost"] * (choices == 0) + rules["coins_gained"] * (choices == 1))
            n = min(int(np.searchsorted(step_counts, rules["steps_per_block"])) + 1, len(choices))
            # The last trial gets no choice (and no coins) if the budget ran out during it
            if n > 0 and step_counts[n - 1] > rules["steps_per_block"]:
                choices[n - 1] = np.nan
                if n > 1:
                    coin_counts[n - 1] = coin_counts[n - 2]

            bound_arr, dt_arr, rt_arr, _, rt_cutoff_arr = get_bounds(
                steps[:n], choices[:n], snr=np.abs(snrs[:n]), block_ids=np.full(n, int(block))
            )
            dfs.append(
                pd.DataFrame(
                    {
                        "subject_index": int(subj),
                        "block_index": int(block),
                        "trial_number": np.arange(1, n + 1),
                        "bound": bound_arr,
                        "RT": rt_arr,
                        "DT": dt_arr,
                        "choice": choices[:n],
                        "correct": choices[:n],  # right is always correct in the simulation
                        "coin_count": coin_counts[:n],
                        "snr": snrs[:n],
                        "steps": steps[:n],
                        "rt_cutoff": rt_cutoff_arr,
                        "rt_below_cutoff": rt_arr < rt_cutoff_arr,
                    }
                )
            )

    sim_table = pd.concat(dfs, ignore_index=True)
    sim_table["abs_bound"] = np.abs(sim_table["bound"])
    sim_table["wall_hit"] = sim_table["steps"].apply(lambda s: len(s) > 0 and bool(np.any(np.abs(s) >= WALL - 1e-9)))
    if correct_bias and os.path.exists(correct_bias):
        sim_table = apply_bias_corrections(sim_table, correct_bias)
    return sim_table
