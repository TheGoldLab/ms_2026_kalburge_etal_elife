"""
Simulation utilities for the Pigeon project.
Python translations of getPigeon_simulatedData.m and getPigeon_simulatedDataTable.m.

Generative model
----------------
Each trial is a 1-D random walk starting at 0.  At every step the position
increments by a sample from N(generative_mean, generative_std).  The trial
ends (boundary crossing) when the absolute position first exceeds a
threshold ``bound``.  An NDT (non-decision time) of additional steps is
added after the crossing to produce the final RT.

Key parameters
--------------
generative_mean : float
    Drift rate.  SNR = generative_mean / generative_std.
generative_std : float
    Per-step noise SD (shared across SNR levels within a simulation).
bound_mean : float
    Mean of the per-trial bound distribution.
bound_std : float
    Trial-to-trial SD of the bound (0 = fixed bound).
ndt_min, ndt_max : int
    Non-decision time drawn uniformly from [ndt_min, ndt_max].
    NDT formula matches MATLAB: randi(hi-lo+1) - lo + 1,
    i.e. Python: rng.integers(1, hi-lo+2) + (1-lo).
ndt_pmf : dict {int: float} or None
    Custom discrete NDT distribution that overrides ndt_min/ndt_max/ndt_sigma.
    Keys are NDT values; values are relative weights (need not sum to 1).
    Example: {2: 1, 4: 1} gives 50 % NDT=2, 50 % NDT=4.

Constants
---------
MIN_BOUND : float
    Floor on the sampled bound (prevents degenerate zero-bound trials).
BLOCK_DEFAULTS : dict
    Per-block step/coin budget defaults, used by ``get_simulated_data_table``
    to truncate simulated blocks to the same step budget as real data.

Usage notes
-----------
- For bias-correction simulations (``BiasCorrection.ipynb``), call
  ``simulate_trials`` directly with ``num_trials=1_000_000``.  Do NOT use
  ``get_simulated_data_table`` for this — it truncates trials via
  ``BLOCK_DEFAULTS['steps_per_block'] = 600``.
- ``get_simulated_data_table`` is designed for fitting/plotting simulations
  that need the same DataFrame format as ``get_data_table``.

Change-point (MXSC) simulation
------------------------------
``simulate_cp_trials`` switches the drift from one SNR to another mid-trial
at the task's change-point step (same indexing as task/MXSC/PigeonTask.js),
optionally with a different bound after the switch.
``get_simulated_cp_data_table`` builds a whole simulated cohort matched to
the real MXSC data (each subject's trial counts, change points, NDT, and
fixed-block bounds) under a stated bound policy -- 'none' (keep the
starting SNR's bound: no strategy change) or 'instant' (switch to the new
SNR's bound at the change point) -- and runs it through the same bound
inference and bias correction as ``get_data_table``. Its purpose is to give
every change-point analysis a simulated "no adaptation" baseline and a
positive control on identical processing.
"""

import os
import numpy as np
import pandas as pd
import scipy.io

from .data import (WALL, get_bounds, apply_bias_corrections, get_good_trial_array,
                   get_cp_generative_params, check_calibration_snrs)
from .pathDefaults import BIAS_CORRECTION_FILE, BIAS_CORRECTION_CP_FILE


MIN_BOUND = 0.03  # minimum allowed bound (prevents degenerate zero-bound trials)

# Per-block reward/penalty defaults (1-indexed block numbers, matching MATLAB blockDefaults)
BLOCK_DEFAULTS = {
    1: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=0),
    2: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=4,  steps_lost=0),
    3: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=30),
    4: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=0),
    5: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=4,  steps_lost=0),
    6: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=30),
    7: dict(steps_per_block=600, p2p_coins=0, coins_gained=1, coins_lost=1,  steps_lost=0),
}

# Same per-condition reward structure as BLOCK_DEFAULTS, but PD's step budget is
# 800/block, not 600 (confirmed from the raw PD CSVs' tc_steps_max field, constant
# across all subjects -- see get_data_table's task_type='PD' handling in data.py).
BLOCK_DEFAULTS_PD = {
    1: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=0),
    2: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=4,  steps_lost=0),
    3: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=30),
    4: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=0),
    5: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=4,  steps_lost=0),
    6: dict(steps_per_block=800, p2p_coins=0, coins_gained=1, coins_lost=0,  steps_lost=30),
}


def simulate_trials(
    generative_mean=0.05,
    generative_std=0.15,
    num_trials=1_000_000,
    max_steps=50,
    bound_mean=0.0,
    bound_std=0.0,
    bound_slope=0.0,
    bound_max=0.75,
    ndt_min=1,
    ndt_max=3,
    ndt_sigma=0.0,
    ndt_center=2.0,
    ndt_bound_slope=0.0,
    lapse_rate=0.0,
    bounds=None,
    sensory_sigma=0.0,
    ndt_pmf=None,
    rng=None,
    return_steps=True,
):
    """
    Simulate Pigeon task trials (core engine).
    Translated from getPigeon_simulatedData.m.

    Parameters
    ----------
    generative_mean : float or array-like
        Mean step size per SNR level. Multiple values are randomly interleaved
        across trials.
    generative_std : float
        SD of each step (shared across all SNR levels).
    num_trials : int
        Number of trials to simulate.
    max_steps : int
        Maximum steps per trial; trial ends even without a boundary crossing.
    bound_mean : float or array-like
        Mean absolute bound. If length == len(generative_mean), each SNR level
        gets its own bound mean.
    bound_std : float or array-like
        Trial-to-trial SD of bound (0 = fixed bound).
    bound_slope : float
        Multiplicative time-varying slope applied linearly over the first 10
        steps, then held constant.
    bound_max : float
        Screen-edge limit (task geometry: 0.75).
    ndt_min, ndt_max : int or array-like
        Non-decision time range (steps).  When ndt_sigma == 0 and
        ndt_bound_slope == 0, drawn uniformly from [ndt_min, ndt_max] using
        the MATLAB-compatible formula.  When ndt_sigma > 0 (and
        ndt_bound_slope == 0), the support is NDT ∈ {ndt_min, …, ndt_max}
        with Gaussian weights exp(-½ ((NDT-2)/ndt_sigma)²) centered at 2.
        If ndt_min/ndt_max are arrays, length must equal len(generative_mean)
        for per-SNR NDTs (ndt_sigma / ndt_bound_slope modes use element [0]).
    ndt_sigma : float
        SD of Gaussian noise added to the per-trial NDT mean.  When > 0 and
        ndt_bound_slope == 0, the mean is fixed at 2 and the support is
        [ndt_min, ndt_max].  When ndt_bound_slope != 0, it is the SD of
        trial-to-trial variability around the bound-dependent mean.
    ndt_center : float
        Intercept of the NDT–bound relationship: NDT_mean = ndt_center +
        ndt_bound_slope × |bound|.  Only used when ndt_bound_slope != 0.
        Set ndt_center = 2 − ndt_bound_slope × ref_bound to anchor the mean
        NDT to 2 at a reference bound level.  Default 2.0.
    ndt_bound_slope : float
        Linear coefficient of NDT vs per-trial |bound| (negative → shorter
        NDT for larger, clearer decisions).  When != 0, activates the
        bound-dependent NDT mode: per-trial NDT_mean = ndt_center +
        ndt_bound_slope × |bound_per_trial|, then optionally jittered by
        ndt_sigma.  NDT is clamped to [1, max_steps − ss − 1].  Requires
        ndt_sigma for trial-to-trial spread around the mean.
    lapse_rate : float
        Fraction of trials assigned a random choice (ignores DV).
    bounds : array-like or None
        If given, per-trial bound is drawn randomly from this pool (overrides
        bound_mean / bound_std).
    sensory_sigma : float
        SD of zero-mean Gaussian perceptual noise added to the true pigeon
        position at each step.  The subject decides to stop based on the
        *perceived* position (true DV + noise), but the step sequences returned
        contain the *true* DV — matching what was actually shown on screen and
        what get_bounds uses to infer the bound.  When > 0 this can trigger
        threshold crossings at true positions that have not yet reached the
        bound, and vice versa.
    ndt_pmf : dict {int: float} or None
        Custom discrete NDT distribution.  Keys are NDT values, values are
        relative weights (need not sum to 1).  When provided, overrides all
        other NDT parameters (ndt_min, ndt_max, ndt_sigma, ndt_bound_slope).
        Example: {2: 0.7, 4: 0.3} draws NDT=2 70% of the time and NDT=4 30%.
    rng : np.random.Generator or None

    Returns
    -------
    choices   : (num_trials,) float array  — 0 or 1 (NaN if no crossing)
    rts       : (num_trials,) int array    — total steps including NDT
    DV        : (num_trials, max_steps+1)  — cumulative step sequences
    bounds_out: (num_trials,) float array  — bound at crossing
    ndts      : (num_trials,) int array    — NDT per trial
    snrs      : (num_trials,) float array  — SNR per trial
    steps     : list of num_trials arrays  — step sequence per trial (TRUE DV)
    """
    if rng is None:
        rng = np.random.default_rng()

    generative_mean = np.atleast_1d(np.asarray(generative_mean, dtype=float))
    n_means = len(generative_mean)

    # Assign each trial a generative mean (interleave randomly if multiple)
    if n_means > 1:
        i_means = rng.integers(0, n_means, size=num_trials)
        trial_means = generative_mean[i_means]
    else:
        i_means = np.zeros(num_trials, dtype=int)
        trial_means = np.full(num_trials, generative_mean[0])

    # NDTs are drawn after bound_per_trial is built (bound-dependent mode needs it).
    # Stored here as a placeholder; filled below.
    ndt_min_arr = np.atleast_1d(np.asarray(ndt_min, dtype=int))
    ndt_max_arr = np.atleast_1d(np.asarray(ndt_max, dtype=int))
    ndts = np.empty(num_trials, dtype=int)

    # Generate DV: starts at 0, each step ~ N(trial_mean, generative_std)
    noise = rng.normal(trial_means[:, None], generative_std,
                       size=(num_trials, max_steps))
    DV = np.concatenate(
        [np.zeros((num_trials, 1)), np.cumsum(noise, axis=1)],
        axis=1,
    )  # shape (num_trials, max_steps + 1)

    # Build per-trial bound values
    bound_mean_arr = np.atleast_1d(np.asarray(bound_mean, dtype=float))
    bound_std_arr  = np.atleast_1d(np.asarray(bound_std,  dtype=float))

    if bounds is not None:
        bounds_arr      = np.asarray(bounds, dtype=float)
        bound_per_trial = bounds_arr[rng.integers(0, len(bounds_arr), size=num_trials)]
    elif len(bound_mean_arr) > 1 and len(bound_mean_arr) == n_means:
        bm = bound_mean_arr[i_means]
        bs = (bound_std_arr[i_means] if len(bound_std_arr) == n_means
              else np.full(num_trials, float(bound_std_arr[0])))
        bound_per_trial = bm.copy()
        variable = bs > 0
        if variable.any():
            bound_per_trial[variable] = np.maximum(
                MIN_BOUND, rng.normal(bm[variable], bs[variable]))
    else:
        bm = float(bound_mean_arr[0])
        bs = float(bound_std_arr[0])
        bound_per_trial = (np.maximum(MIN_BOUND, rng.normal(bm, bs, size=num_trials))
                           if bs > 0 else np.full(num_trials, bm))

    # Draw NDTs (now that bound_per_trial is available for bound-dependent mode)
    if ndt_pmf is not None:
        values  = np.array(sorted(ndt_pmf.keys()), dtype=int)
        weights = np.array([ndt_pmf[v] for v in values], dtype=float)
        weights /= weights.sum()
        ndts[:] = rng.choice(values, size=num_trials, p=weights)
    elif ndt_bound_slope != 0.0:
        # Per-trial NDT mean scales linearly with |bound|:
        #   NDT_mean = ndt_center + ndt_bound_slope * |bound|
        # Negative ndt_bound_slope → shorter NDT for larger, clearer decisions.
        ndt_means = ndt_center + ndt_bound_slope * bound_per_trial
        ndt_means = np.maximum(ndt_means, 1.0)
        raw = (rng.normal(ndt_means, ndt_sigma) if ndt_sigma > 0
               else ndt_means)
        ndts[:] = np.maximum(np.round(raw).astype(int), 1)
    elif ndt_sigma > 0:
        # Gaussian-weighted discrete distribution centered at NDT=2.
        lo, hi = int(ndt_min_arr[0]), int(ndt_max_arr[0])
        support  = np.arange(lo, hi + 1)
        weights  = np.exp(-0.5 * ((support - 2.0) / ndt_sigma) ** 2)
        weights /= weights.sum()
        ndts[:] = rng.choice(support, size=num_trials, p=weights)
    else:
        # Original MATLAB-compatible uniform formula.
        if len(ndt_min_arr) == 1 or len(ndt_min_arr) != n_means:
            lo, hi = int(ndt_min_arr[0]), int(ndt_max_arr[0])
            ndts[:] = rng.integers(1, hi - lo + 2, size=num_trials) + (1 - lo)
        else:
            for mm in range(n_means):
                lm = i_means == mm
                lo, hi = int(ndt_min_arr[mm]), int(ndt_max_arr[mm])
                ndts[lm] = rng.integers(1, hi - lo + 2, size=int(lm.sum())) + (1 - lo)

    # Build slope vector for time-varying bound (covers columns 0..max_steps-1,
    # the only columns checked for crossings). Skipped when bound_slope == 0.
    if bound_slope != 0:
        n_col = max_steps + 1
        slope_vec = np.concatenate([
            np.linspace(1.0, bound_slope, min(10, n_col)),
            np.full(max(n_col - 10, 0), bound_slope),
        ])[:max_steps]

    # Find first bound crossings — fully vectorized, no Python step loop.
    # When sensory_sigma > 0, crossing detection and choice use the *perceived*
    # DV (true DV + i.i.d. Gaussian noise); step sequences remain the true DV.
    choices_out = np.full(num_trials, np.nan)
    rts_out     = np.full(num_trials, max_steps, dtype=int)
    bounds_out  = np.full(num_trials, np.nan)
    snrs        = trial_means / generative_std
    abs_DV      = np.abs(DV)

    if sensory_sigma > 0:
        perceptual_noise = rng.normal(0, sensory_sigma,
                                      size=(num_trials, max_steps))
        perceived_DV  = DV[:, :max_steps] + perceptual_noise
        abs_perceived = np.abs(perceived_DV)
    else:
        perceived_DV  = DV[:, :max_steps]
        abs_perceived = abs_DV[:, :max_steps]

    if bound_slope != 0:
        crossed_at = abs_perceived >= bound_per_trial[:, None] * slope_vec[None, :]
    else:
        crossed_at = abs_perceived >= bound_per_trial[:, None]

    any_crossed = crossed_at.any(axis=1)
    first_ss    = np.argmax(crossed_at, axis=1)  # meaningful only where any_crossed

    # Normal crossings (ss > 0; the common path — requires bound > 0)
    normal = any_crossed & (first_ss > 0)
    if normal.any():
        rows    = np.where(normal)[0]
        ss_vals = first_ss[rows]
        # Clamp NDT so DT ≥ 1 (NDT ≥ 1) and RT ≤ max_steps (NDT ≤ max_steps-ss-1)
        ndts[rows] = np.clip(ndts[rows], 1, max_steps - ss_vals - 1)
        rts_out[rows]     = ss_vals + ndts[rows] + 1   # guaranteed ≤ max_steps
        # Choice direction from PERCEIVED DV (what triggered the crossing)
        choices_out[rows] = (perceived_DV[rows, ss_vals] > 0).astype(float)
        bounds_out[rows]  = (bound_per_trial[rows] * slope_vec[ss_vals]
                             if bound_slope != 0 else bound_per_trial[rows])

    # ss=0 crossings: only reachable when bound == 0; assign random RT and choice
    ss0 = any_crossed & (first_ss == 0)
    if ss0.any():
        n_ss0 = int(ss0.sum())
        rts_out[ss0]     = rng.integers(1, 3, size=n_ss0)
        choices_out[ss0] = rng.integers(0, 2, size=n_ss0).astype(float)
        bounds_out[ss0]  = (bound_per_trial[ss0] * slope_vec[0]
                            if bound_slope != 0 else bound_per_trial[ss0])

    # Build steps_list: each element is the cumulative DV path for one trial,
    # truncated at RT.  This matches the format of pigeon_steps in the real data
    # and is consumed by get_bounds / infer_bound_mean_per_dt.
    # Pass return_steps=False to skip this allocation (e.g., BiasCorrection.ipynb).
    if return_steps:
        steps_list = [DV[tt, : rts_out[tt]] for tt in range(num_trials)]
    else:
        steps_list = None

    # Lapses: override a random fraction of choices
    if lapse_rate > 0:
        n_lapse   = int(np.ceil(lapse_rate * num_trials))
        lapse_idx = rng.integers(0, num_trials, size=n_lapse)
        choices_out[lapse_idx] = rng.integers(0, 2, size=n_lapse).astype(float)

    return choices_out, rts_out, DV, bounds_out, ndts, snrs, steps_list


def get_simulated_data_table(
    data_table=None,
    specs=None,
    generative_mean=0.05,
    generative_std=0.15,
    num_trials=600,
    max_steps=50,
    bound_mean=0.0,
    bound_std=0.0,
    bound_slope=0.0,
    bound_max=0.75,
    ndt_min=2,
    ndt_max=3,
    ndt_sigma=0.0,
    ndt_center=2.0,
    ndt_bound_slope=0.0,
    lapse_rate=0.0,
    bound_type='given',
    bounds=None,
    sensory_sigma=0.0,
    ndt_pmf=None,
    correct_bias=BIAS_CORRECTION_FILE,
    rng=None,
    var_bound_std=None,
    block_defaults=BLOCK_DEFAULTS,
):
    """
    Simulate a data table matching the format of get_data_table().
    Translated from getPigeon_simulatedDataTable.m.

    Call modes
    ----------
    data_table mode  (pass data_table)
        Infers per-subject/block generative_mean, NDT, and bound parameters
        from the real data according to bound_type.
    specs mode       (pass specs dict)
        Parametric simulation; all subjects share the same keyword-argument
        parameters.

    Parameters
    ----------
    data_table : pd.DataFrame or None
    specs : dict or None
        Keys: 'num_subjects' (int), 'blocks' (int or list of ints).
    generative_mean : float or array-like
        Mean step size. In specs mode, typically a single positive value
        equal to SNR × generative_std.
    generative_std : float
    num_trials : int
        Maximum trials simulated; actual count is capped at the step budget.
    max_steps : int
        Maximum steps per trial.
    bound_mean : float or array-like
    bound_std : float or array-like
    bound_slope : float
    bound_max : float
    ndt_min, ndt_max : int or array-like
    lapse_rate : float
    bound_type : {'given', 'fixed', 'true', 'var'}
        (data_table mode only)
        'given'  – use the passed bound_mean / bound_std unchanged
        'fixed'  – median |bound| per subject/block; bound_std = 0
        'true'   – sample per-trial bounds from actual data; bound_std = 0
        'var'    – median + std of |bound| per subject/block; the std can be
                   overridden for every subject/block via `var_bound_std`
        Note: in specs mode, per-SNR bounds can be achieved by passing
        generative_mean and bound_mean as matching-length lists (e.g.
        generative_mean=[lo, hi], bound_mean=[b_lo, b_hi]).  simulate_trials
        then assigns each trial the bound corresponding to its SNR level.
        This is equivalent to MATLAB's boundType='varBySNR'.
    bounds : array-like or None
    sensory_sigma : float
    ndt_pmf : dict {int: float} or None
        Custom discrete NDT distribution forwarded to simulate_trials.
        Overrides ndt_min, ndt_max, ndt_sigma, ndt_bound_slope when set.
    correct_bias : str or None
        Path to .mat bias-correction file; applied if the file exists.
    rng : np.random.Generator or None
    var_bound_std : float or None
        (data_table mode, bound_type='var' only) When set, overrides the
        per-subject/block empirical std of |bound| with this single shared
        value for every subject/block, while bound_mean stays each subject's
        own empirical median |bound|. Used to fit the bound SD as a free
        parameter shared across subjects. Ignored unless bound_type='var'.
    block_defaults : dict
        Per-block step budget and reward structure, keyed by block number
        (see BLOCK_DEFAULTS). Default BLOCK_DEFAULTS (600 steps/block, the
        OL/MX/MXSC task). Pass BLOCK_DEFAULTS_PD for the PD task (800
        steps/block, same per-condition reward structure otherwise).

    Returns
    -------
    pd.DataFrame with columns matching get_data_table() output.
    """
    if rng is None:
        rng = np.random.default_rng()

    # Base simulation kwargs, shared unless overridden per subject/block
    base = dict(
        generative_mean=generative_mean,
        generative_std=generative_std,
        num_trials=num_trials,
        max_steps=max_steps,
        bound_mean=bound_mean,
        bound_std=bound_std,
        bound_slope=bound_slope,
        bound_max=bound_max,
        ndt_min=ndt_min,
        ndt_max=ndt_max,
        ndt_sigma=ndt_sigma,
        ndt_center=ndt_center,
        ndt_bound_slope=ndt_bound_slope,
        lapse_rate=lapse_rate,
        bounds=bounds,
        sensory_sigma=sensory_sigma,
        ndt_pmf=ndt_pmf,
    )

    # ------------------------------------------------------------------
    # Build per-subject × per-block spec dicts
    # ------------------------------------------------------------------
    if data_table is not None:
        subjects = np.sort(data_table['subject_index'].dropna().unique())
        blocks   = np.sort(data_table['block_index'].dropna().unique().astype(int))
        abs_snr  = np.abs(data_table['snr'].to_numpy())
        abs_b    = np.abs(data_table['bound'].to_numpy())
        lg       = data_table['bound'].notna() & (data_table['RT'] >= 0)

        block_specs = [[dict(base) for _ in blocks] for _ in subjects]

        for si, subj in enumerate(subjects):
            ls_sub = data_table['subject_index'] == subj
            for bi, block in enumerate(blocks):
                spec = block_specs[si][bi]
                spec.update(block_defaults.get(int(block), block_defaults[1]))

                ls_blk   = lg & ls_sub & (data_table['block_index'] == block)
                snr_vals = np.unique(abs_snr[ls_blk & np.isfinite(abs_snr)])
                spec['generative_mean'] = snr_vals * generative_std

                # NDT: derived from congruence on block 1, then copied to later blocks
                if bi == 0:
                    first_idx = ls_sub[ls_sub].index[0]
                    cong = data_table.loc[first_idx, 'congruence']
                    if (cong is not None and isinstance(cong, np.ndarray)
                            and cong.ndim == 2 and cong.shape[1] >= len(snr_vals)):
                        ndt_min_v = np.empty(len(snr_vals), dtype=int)
                        ndt_max_v = np.empty(len(snr_vals), dtype=int)
                        for ni in range(len(snr_vals)):
                            order = np.argsort(cong[:, ni])
                            top2  = order[-2:]
                            # +1 converts 0-indexed Python lag positions to MATLAB's 1-indexed NDT
                            ndt_min_v[ni] = int(top2.min()) + 1
                            ndt_max_v[ni] = int(top2.max()) + 1
                        spec['ndt_min'] = ndt_min_v
                        spec['ndt_max'] = ndt_max_v
                else:
                    spec['ndt_min'] = block_specs[si][0]['ndt_min']
                    spec['ndt_max'] = block_specs[si][0]['ndt_max']

                # Bound parameters according to bound_type
                ab = abs_b[ls_blk]
                ab = ab[np.isfinite(ab)]
                if bound_type == 'fixed':
                    spec['bound_mean'] = float(np.nanmedian(ab))
                    spec['bound_std']  = 0.0
                elif bound_type == 'true':
                    spec['bounds']    = ab
                    spec['bound_std'] = 0.0
                elif bound_type == 'var':
                    spec['bound_mean'] = float(np.nanmedian(ab))
                    spec['bound_std']  = (float(np.nanstd(ab)) if var_bound_std is None
                                           else float(var_bound_std))
                # 'given': leave base values unchanged

    elif specs is not None:
        blocks_arr = np.atleast_1d(np.asarray(specs.get('blocks', [1]), dtype=int))
        n_subjects = int(specs.get('num_subjects', 1))
        subjects   = np.arange(1, n_subjects + 1)
        blocks     = blocks_arr

        block_specs = []
        for _ in subjects:
            row = []
            for block in blocks:
                spec = dict(base)
                spec.update(block_defaults.get(int(block), block_defaults[1]))
                row.append(spec)
            block_specs.append(row)

    else:
        raise ValueError("Provide either data_table or specs.")

    # ------------------------------------------------------------------
    # Run simulations and assemble output rows
    # ------------------------------------------------------------------
    dfs = []

    for si, subj in enumerate(subjects):
        for bi, block in enumerate(blocks):
            spec = block_specs[si][bi]
            bd = {k: spec[k] for k in
                  ('steps_per_block', 'p2p_coins', 'coins_gained', 'coins_lost', 'steps_lost')}
            sim_kw = {k: spec[k] for k in (
                'generative_mean', 'generative_std', 'num_trials', 'max_steps',
                'bound_mean', 'bound_std', 'bound_slope', 'bound_max',
                'ndt_min', 'ndt_max', 'ndt_sigma', 'ndt_center', 'ndt_bound_slope',
                'lapse_rate', 'bounds', 'sensory_sigma', 'ndt_pmf',
            )}

            choices, rts, _DV, _b, _ndts, snrs_sim, steps_sim = simulate_trials(
                **sim_kw, rng=rng,
            )
            n_sim = len(choices)

            # Cumulative steps and coins; truncate when the step budget is reached
            step_counts = np.cumsum(rts + bd['steps_lost'] * (choices == 0))
            coin_counts = np.cumsum(
                -bd['p2p_coins']
                - bd['coins_lost']  * (choices == 0)
                + bd['coins_gained'] * (choices == 1)
            )

            idx         = int(np.searchsorted(step_counts, bd['steps_per_block']))
            trial_count = min(idx + 1, n_sim)

            # Mark last trial as aborted (NaN choice) if budget was exceeded mid-trial
            if trial_count > 0 and step_counts[trial_count - 1] > bd['steps_per_block']:
                choices[trial_count - 1] = np.nan
                if trial_count > 1:
                    coin_counts[trial_count - 1] = coin_counts[trial_count - 2]

            ch = choices[:trial_count]
            sn = snrs_sim[:trial_count]
            st = steps_sim[:trial_count]
            cc = coin_counts[:trial_count]

            # Compute bound and DT from step sequences (same pipeline as real data)
            bound_arr, dt_arr, rt_arr, _, rt_cutoff_arr = get_bounds(
                st, ch, snr=np.abs(sn),
                block_ids=np.full(trial_count, int(block))
            )

            # Build one DataFrame per (subject, block) — faster than appending one dict per trial
            dfs.append(pd.DataFrame({
                'subject_index':  int(subj),
                'block_index':    int(block),
                'trial_number':   np.arange(1, trial_count + 1),
                'bound':          bound_arr,
                'RT':             rt_arr,
                'DT':             dt_arr,
                'choice':         ch,
                'correct':        ch,   # equals choice when generative_mean > 0
                'coin_count':     cc,
                'snr':            sn,
                'steps':          st,
                'rt_cutoff':      rt_cutoff_arr,
                'rt_below_cutoff': rt_arr < rt_cutoff_arr,
            }))

    sim_table = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    if len(sim_table) == 0:
        return sim_table

    sim_table['abs_bound'] = np.abs(sim_table['bound'])
    sim_table['wall_hit']  = sim_table['steps'].apply(
        lambda s: (s is not None and len(s) > 0
                   and bool(np.any(np.abs(s[np.isfinite(s)]) >= WALL - 1e-9)))
    )

    if correct_bias and os.path.exists(correct_bias):
        sim_table = apply_bias_corrections(sim_table, correct_bias)

    return sim_table


def simulate_cp_trials(pre_mean, post_mean, generative_std, cp_step, num_trials,
                       bound_pre, bound_post=None, bound_std=0.0, ndt=1,
                       max_steps=50, rng=None):
    """Simulate change-point (MXSC) trials: the drift switches SNR mid-trial.

    Each trial's direction (sign of the drift) is drawn 50/50 and kept across
    the switch, as in the fixed task code. The accumulator stops when |DV|
    first reaches the bound in force at that position; NDT steps follow.

    Parameters
    ----------
    pre_mean, post_mean : float
        Unsigned per-step generative means before and after the change point.
    generative_std : float
        Per-step noise SD (same before and after).
    cp_step : int or None
        Change-point step (the trial's switch_time). The task switches SNR
        just before its cp_step-th movement, so movements cp_step, cp_step+1,
        ... use post_mean. None or 0 means no switch (a fixed-SNR block).
    num_trials : int
        Number of trials.
    bound_pre : float
        Mean bound for positions reached before the switch.
    bound_post : float or None
        Mean bound for positions reached after the switch. None (default)
        keeps bound_pre, i.e. no adaptation to the change point.
    bound_std : float
        Trial-to-trial SD of the bound. One N(0, 1) draw per trial scales both
        bound_pre and bound_post, so a cautious trial is cautious throughout.
    ndt : int
        Non-decision steps after the crossing (the lag get_bounds estimates).
    max_steps : int
        Maximum positions per trial (task: STEPS_MAX_PER_TRIAL = 50).
    rng : np.random.Generator or None

    Returns
    -------
    dict
        choice (1 = right, 0 = left, NaN = no crossing), correct (1/0, NaN
        with choice), RT (positions logged, = len(steps)), steps (list of
        position arrays starting at 0, the format of pigeon_steps), snr
        (signed starting SNR), bound (bound in force at the crossing).
    """
    if rng is None:
        rng = np.random.default_rng()
    if bound_post is None:
        bound_post = bound_pre
    cp = int(cp_step) if cp_step else 0

    sign = rng.choice([-1.0, 1.0], size=num_trials)
    # Noise column m is movement m+1; movements >= cp (columns >= cp-1) run at post_mean.
    cols = np.arange(max_steps)
    no_switch = np.zeros(max_steps, dtype=bool)
    move_mean = np.where((cols >= cp - 1) if cp else no_switch, post_mean, pre_mean)
    noise = rng.normal(0.0, generative_std, size=(num_trials, max_steps)) + sign[:, None] * move_mean
    DV = np.concatenate([np.zeros((num_trials, 1)), np.cumsum(noise, axis=1)], axis=1)

    # DV column j is the position after j movements, so positions j >= cp were
    # reached under the new SNR and are compared against bound_post.
    z = rng.standard_normal(num_trials) if bound_std > 0 else np.zeros(num_trials)
    pos_bound = np.where((cols >= cp) if cp else no_switch, bound_post, bound_pre)
    bound = np.maximum(MIN_BOUND, pos_bound[None, :] + bound_std * z[:, None])
    crossed = np.abs(DV[:, :max_steps]) >= bound
    crossed[:, 0] = False  # start position; unreachable anyway since bound >= MIN_BOUND > 0

    any_crossed = crossed.any(axis=1)
    first_ss = np.argmax(crossed, axis=1)
    rows = np.flatnonzero(any_crossed)
    ss = first_ss[rows]

    choice = np.full(num_trials, np.nan)
    rts = np.full(num_trials, max_steps, dtype=int)
    bound_out = np.full(num_trials, np.nan)
    # Same NDT clamp and RT convention as simulate_trials: RT = crossing + NDT + 1 <= max_steps.
    rts[rows] = ss + np.clip(ndt, 1, max_steps - ss - 1) + 1
    choice[rows] = (DV[rows, ss] > 0).astype(float)
    bound_out[rows] = bound[rows, ss]
    correct = np.where(np.isfinite(choice), (choice == (sign > 0)).astype(float), np.nan)

    return {
        "choice": choice,
        "correct": correct,
        "RT": rts,
        "steps": [DV[tt, :rts[tt]] for tt in range(num_trials)],
        "snr": sign * pre_mean / generative_std,
        "bound": bound_out,
    }


def get_simulated_cp_data_table(data_table, bound_std=0.0, adapt="none", max_steps=50,
                                correct_bias=BIAS_CORRECTION_CP_FILE, rng=None):
    """Simulate an MXSC cohort matched to real data, under a stated bound policy.

    For each subject with all four canonical blocks (1 Low, 2 High, 3 LowHigh,
    4 HighLow), simulates the same number of trials per block at the data's
    own generative means (get_cp_generative_params), using the subject's own
    change points and NDT. The subject's bound at each SNR is their median
    |bound| in the matching fixed block. The simulated steps then go through
    the same bound inference (get_bounds) and bias correction as
    get_data_table, so any analysis can be run on real and simulated tables
    alike.

    Parameters
    ----------
    data_table : pd.DataFrame
        Real MXSC table from get_data_table (bias-corrected), the source of
        each subject's trial counts, change points, NDT, and fixed-block bounds.
    bound_std : float
        Trial-to-trial SD of the bound (see simulate_cp_trials).
    adapt : {'none', 'instant'}
        Bound policy in the change-point blocks. 'none': keep the starting
        SNR's bound all trial (no strategy change). 'instant': switch to the
        new SNR's fixed-block bound at the change point.
    max_steps : int
        Maximum positions per trial.
    correct_bias : str, Path, or None
        CP bias-correction file, checked against the data's SNRs and applied
        as in get_data_table. None skips correction.
    rng : np.random.Generator or None

    Returns
    -------
    pd.DataFrame
        Same core columns as get_data_table: subject_index, block_index,
        trial_number, bound, abs_bound, RT, DT, choice, correct, snr,
        step_std, change_point, steps, rt_cutoff, rt_below_cutoff, wall_hit.
    """
    if adapt not in ("none", "instant"):
        raise ValueError(f"adapt must be 'none' or 'instant', got {adapt!r}")
    if rng is None:
        rng = np.random.default_rng()

    gen = get_cp_generative_params(data_table)
    g_std = gen["low"][1]
    lg = get_good_trial_array(data_table) & (data_table["correct"] >= 0)

    dfs = []
    for subj, sub in data_table.groupby("subject_index"):
        if set(sub["block_index"].dropna().astype(int)) < {1, 2, 3, 4}:
            continue  # dropouts: no CP blocks to compare
        lsub = lg.loc[sub.index]
        b_low = np.nanmedian(sub.loc[lsub & (sub["block_index"] == 1), "bound"].abs())
        b_high = np.nanmedian(sub.loc[lsub & (sub["block_index"] == 2), "bound"].abs())
        if not (np.isfinite(b_low) and np.isfinite(b_high)):
            continue
        # NDT = RT - DT - 1 (get_bounds' DT convention); one lag per subject.
        ndt = int((sub["RT"] - sub["DT"] - 1).dropna().mode().iloc[0])

        # block: (pre mean, post mean, pre bound, post bound under each policy)
        designs = {
            1: (gen["low"][0], gen["low"][0], b_low, b_low),
            2: (gen["high"][0], gen["high"][0], b_high, b_high),
            3: (gen["low"][0], gen["high"][0], b_low, b_high if adapt == "instant" else b_low),
            4: (gen["high"][0], gen["low"][0], b_high, b_low if adapt == "instant" else b_high),
        }
        parts = []
        for block, (m_pre, m_post, b_pre, b_post) in designs.items():
            blk = sub[sub["block_index"] == block]
            cp = blk["change_point"].dropna().unique() if block in (3, 4) else [0]
            if len(cp) != 1 or not np.isfinite(cp[0]):
                break  # no usable change point for this subject
            sim = simulate_cp_trials(m_pre, m_post, g_std, int(cp[0]), len(blk), b_pre, b_post,
                                     bound_std=bound_std, ndt=ndt, max_steps=max_steps, rng=rng)
            parts.append(pd.DataFrame({
                "subject_index": subj, "block_index": block,
                "trial_number": np.arange(1, len(blk) + 1),
                "choice": sim["choice"], "correct": sim["correct"], "snr": sim["snr"],
                "step_std": g_std, "change_point": float(cp[0]), "steps": sim["steps"],
            }))
        else:
            sub_sim = pd.concat(parts, ignore_index=True)
            # Same get_bounds call as get_data_table's (one call per subject over all
            # blocks, NDT estimated from the lowest-SNR trials).
            bounds, dts, rts, _, rt_cutoffs = get_bounds(
                list(sub_sim["steps"]), sub_sim["choice"].to_numpy(),
                snr=np.abs(sub_sim["snr"].to_numpy()), block_ids=sub_sim["block_index"].to_numpy(),
                ndt=None, max_ndt=5, peak_step_bound=True,
            )
            sub_sim["bound"], sub_sim["DT"], sub_sim["RT"], sub_sim["rt_cutoff"] = bounds, dts, rts, rt_cutoffs
            dfs.append(sub_sim)

    sim_table = pd.concat(dfs, ignore_index=True)
    sim_table["abs_bound"] = np.abs(sim_table["bound"])
    sim_table["rt_below_cutoff"] = sim_table["RT"] < sim_table["rt_cutoff"]
    sim_table["wall_hit"] = sim_table["steps"].apply(
        lambda s: len(s) > 0 and bool(np.any(np.abs(s) >= WALL - 1e-9)))
    if correct_bias and os.path.exists(correct_bias):
        calib = scipy.io.loadmat(correct_bias, squeeze_me=True)
        check_calibration_snrs(calib["snrs"], sim_table, source=correct_bias)
        sim_table = apply_bias_corrections(sim_table, correct_bias)
    return sim_table
