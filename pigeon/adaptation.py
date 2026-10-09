"""
Within-block adaptation time-constant (tau) fits.

Shared by ``Figure04_RRvsBound`` (source of the tau insets in panels D-F) and
any other notebook that needs to gate trials on a subject's own within-block
adaptation time constant (e.g. ``Figure03S04_sequentialAnalysis``). Extracted
from ``Figure04_RRvsBound`` so both notebooks fit tau from the same pipeline,
with the same eligibility criteria, on the same data.

Pipeline
--------
1. ``compute_per_subject_curves_with_nulls`` — per-subject, per-block smoothed
   z-scored |bound| curve over the first ``max_trial`` trials, plus a bank of
   trial-order permutation nulls (same subject, same block, shuffled order).
2. ``per_subject_significance`` / ``group_null_band`` — is a subject's curve
   (or the group-mean curve) distinguishable from the permutation null?
3. ``between_block_significance`` — for blocks after the first, does a
   subject's steady-state |bound| differ from the immediately preceding
   block? Used as the tau-fit eligibility criterion for blocks 2+ (block 1
   has no preceding block, so it uses the within-block test instead).
4. ``fit_exp_tau`` — fit ``A*exp(-t/tau)+C`` to an eligible subject's curve.
5. ``get_adaptation_tau_fits`` — orchestrates the above and returns, per
   subject and block, the tau only for "good" fits: eligible, converged
   within the fit window (not censored at ``max_trial``), values elsewhere
   are NaN.
"""

import numpy as np
import pandas as pd
import scipy.stats
from scipy.optimize import curve_fit

from .data import get_good_trial_array


def _build_window_matrix(t_vals, trial_nums, half_win, min_win):
    """
    Precompute the trial-window averaging weights for one subject x block.
    These weights only depend on which raw trial numbers exist (t_vals), not on the
    bound values themselves, so the same matrix can be reused for the real curve and
    for every permutation of that subject's z values.
    """
    n_bins = len(trial_nums)
    W = np.zeros((n_bins, len(t_vals)))
    lvalid = np.zeros(n_bins, dtype=bool)
    for ti, t in enumerate(trial_nums):
        mask = (t_vals >= t - half_win) & (t_vals <= t + half_win)
        cnt = mask.sum()
        if cnt >= min_win:
            W[ti, mask] = 1.0 / cnt
            lvalid[ti] = True
    return W, lvalid


def _exp_decay(t, A, tau, C):
    return A * np.exp(-t / tau) + C


def fit_exp_tau(trial_nums, z_vals, tau_max, min_valid=8):
    """
    Fit A*exp(-t/tau)+C to a single subject/block's smoothed curve.

    Parameters
    ----------
    trial_nums : (n,) array
        Trial-number x-values.
    z_vals : (n,) array
        Smoothed z-scored curve values (may contain NaN).
    tau_max : float
        Upper bound passed to the optimizer; also the value that marks a fit
        as censored (see Returns).
    min_valid : int
        Minimum number of finite z_vals required to attempt a fit. Default 8.

    Returns
    -------
    tau : float
        Fitted time constant, or NaN on failure / insufficient data.
    censored : bool
        True if the fit hit the tau_max boundary, i.e. the optimizer found
        no resolvable decay within the fit window (slow drift, not a fast
        settle) -- these tau values describe a lower bound, not a measurement.
    """
    lvalid = np.isfinite(z_vals)
    if lvalid.sum() < min_valid:
        return np.nan, False
    t = trial_nums[lvalid].astype(float)
    y = z_vals[lvalid]
    A0 = float(y[0] - np.nanmedian(y[-5:]))
    C0 = float(np.nanmedian(y[-5:]))
    try:
        popt, _ = curve_fit(
            _exp_decay, t, y,
            p0=[A0, 10.0, C0],
            bounds=([-np.inf, 0.5, -np.inf], [np.inf, tau_max, np.inf]),
            maxfev=5000,
        )
        tau = float(popt[1])
        return tau, tau >= tau_max - 1e-6
    except Exception:
        return np.nan, False


def compute_per_subject_curves_with_nulls(data_table, max_trial, blocks,
                                           half_win=3, min_win=3,
                                           n_perm=1000, seed=123):
    """
    For every subject x block, computes the real smoothed z-scored bound curve plus
    a bank of permutation-null curves (trial order shuffled within that subject's own
    block, so each null preserves the subject's own noise level but has no time-locked
    structure). The same null bank is used downstream both for per-subject significance
    testing and for the group-level null band.

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table.
    max_trial : int
        Number of trial-number x-values to compute the curve over (1..max_trial).
    blocks : list of int
        Block indices to compute curves for.
    half_win : int
        Half-width (in trials) of the smoothing window. Default 3.
    min_win : int
        Minimum number of trials required within a smoothing window for that
        x-value to be valid (not NaN). Default 3.
    n_perm : int
        Number of trial-order permutation nulls per subject/block. Default 1000.
    seed : int
        Seed for the permutation RNG. Default 123.

    Returns
    -------
    trial_nums  : (max_trial,) int array
    real_curves : (n_subjects, max_trial, n_blocks)
    perm_curves : (n_perm, n_subjects, max_trial, n_blocks)
    subjects    : list of subject indices
    """
    subjects = sorted(data_table['subject_index'].dropna().unique())
    trial_nums = np.arange(1, max_trial + 1)
    rng = np.random.default_rng(seed)

    real_curves = np.full((len(subjects), max_trial, len(blocks)), np.nan)
    perm_curves = np.full((n_perm, len(subjects), max_trial, len(blocks)), np.nan)

    for bi, block in enumerate(blocks):
        # Standard DT >= 2 quality filter (project default). min_trial_number
        # is intentionally left at None (not the standard >= 10 floor): trial_number
        # *is* the x-axis of the curve being fit here, so a floor of 10 would
        # remove the first 9 trials of every block and make it impossible to see
        # the early-trial settling dynamics this curve exists to characterize.
        lg = get_good_trial_array(
            data_table, min_trial_number=None, block_index=block)
        block_data = data_table[lg]

        for si, subj in enumerate(subjects):
            sd = block_data[block_data['subject_index'] == subj]
            if sd['abs_bound'].dropna().shape[0] < 2:
                continue
            mu = sd['abs_bound'].mean()
            sigma = sd['abs_bound'].std()
            if sigma < 1e-10:
                continue
            z = (sd['abs_bound'].values - mu) / sigma
            t_vals = sd['trial_number'].values

            W, lvalid = _build_window_matrix(t_vals, trial_nums, half_win, min_win)

            curve = W @ z
            curve[~lvalid] = np.nan
            real_curves[si, :, bi] = curve

            z_tiled = np.broadcast_to(z, (n_perm, len(z))).copy()
            z_shuf = rng.permuted(z_tiled, axis=1)
            perm = z_shuf @ W.T
            perm[:, ~lvalid] = np.nan
            perm_curves[:, si, :, bi] = perm

    return trial_nums, real_curves, perm_curves, subjects


def per_subject_significance(real_curves, perm_curves, alpha=0.05):
    """
    Permutation test: does the real smoothed curve deviate from zero more than expected
    by chance? Test statistic = sum of squared curve values across the trial window.

    Parameters
    ----------
    real_curves : (n_subjects, max_trial, n_blocks) array
        Real smoothed z-scored bound curves, from compute_per_subject_curves_with_nulls.
    perm_curves : (n_perm, n_subjects, max_trial, n_blocks) array
        Permutation-null curves, from compute_per_subject_curves_with_nulls.
    alpha : float
        Significance threshold. Default 0.05.

    Returns
    -------
    pvals : (n_subjects, n_blocks) array
    sig   : (n_subjects, n_blocks) bool array
    """
    lhas_data = np.any(np.isfinite(real_curves), axis=1)
    obs_stat = np.nansum(real_curves ** 2, axis=1)
    perm_stat = np.nansum(perm_curves ** 2, axis=2)
    counts = np.sum(perm_stat >= obs_stat[None, :, :], axis=0)
    pvals = (1 + counts) / (1 + perm_stat.shape[0])
    pvals = np.where(lhas_data, pvals, np.nan)
    lsig = pvals < alpha
    return pvals, lsig


def group_null_band(perm_curves, alpha=0.05):
    """
    Max-stat (Tmax) permutation threshold for the group-mean curve: average the null
    curves across subjects within each permutation iteration, take the max absolute
    deviation over all trials in that iteration, then take the alpha-level percentile
    across iterations. This single threshold is corrected for the multiple-comparison
    problem across the trial timepoints.

    Parameters
    ----------
    perm_curves : (n_perm, n_subjects, max_trial, n_blocks) array
        Permutation-null curves, from compute_per_subject_curves_with_nulls.
    alpha : float
        Significance level for the max-stat threshold. Default 0.05.

    Returns
    -------
    np.ndarray, shape (n_blocks,)
        Per-block max-stat threshold.
    """
    group_null = np.nanmean(perm_curves, axis=1)        # (n_perm, max_trial, n_blocks)
    max_stat = np.nanmax(np.abs(group_null), axis=1)    # (n_perm, n_blocks)
    return np.percentile(max_stat, 100 * (1 - alpha), axis=0)


def between_block_significance(data_table, blocks, alpha=0.05, min_trials=5):
    """
    Per-subject test of whether steady-state |bound| differs between block[i-1] and
    block[i] (i = 1 .. len(blocks)-1). Uses the same default trial-quality filtering as
    get_bound_summary (DT>=2, trial_number>=10, wall_hit and rt_below_cutoff excluded) --
    i.e. this is the same steady-state bound quantity compared in the block-vs-block
    scatter plots earlier in this notebook, but tested per subject with an unpaired,
    two-sided Mann-Whitney U test (no normality assumption) instead of only at the
    group level.

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table.
    blocks : list of int
        Block indices, in order; block[i] is compared against block[i-1]
        for i = 1 .. len(blocks)-1.
    alpha : float
        Significance threshold. Default 0.05.
    min_trials : int
        Minimum trials required in each of the two compared blocks for a
        subject to be tested. Default 5.

    Returns
    -------
    pvals : (n_subjects, n_blocks) -- column 0 is NaN (no preceding block to compare)
    sig   : (n_subjects, n_blocks) bool -- column 0 is always False
    """
    subjects = sorted(data_table['subject_index'].dropna().unique())
    n_subjects = len(subjects)
    n_blocks = len(blocks)
    pvals = np.full((n_subjects, n_blocks), np.nan)
    lsig = np.zeros((n_subjects, n_blocks), dtype=bool)

    lg_by_block = {block: get_good_trial_array(data_table, block_index=block) for block in blocks}

    for bi in range(1, n_blocks):
        lg_prev = lg_by_block[blocks[bi - 1]]
        lg_cur = lg_by_block[blocks[bi]]

        for si, subj in enumerate(subjects):
            subj_mask = data_table['subject_index'] == subj
            x_prev = data_table.loc[subj_mask & lg_prev, 'abs_bound'].dropna().to_numpy()
            x_cur = data_table.loc[subj_mask & lg_cur, 'abs_bound'].dropna().to_numpy()
            if len(x_prev) < min_trials or len(x_cur) < min_trials:
                continue
            try:
                _, p = scipy.stats.mannwhitneyu(x_prev, x_cur, alternative='two-sided')
            except ValueError:
                continue
            pvals[si, bi] = p
            lsig[si, bi] = p < alpha

    return pvals, lsig


def get_adaptation_tau_fits(data_table, blocks=(1, 2, 3), max_trial=40,
                            half_win=3, min_win=3, n_perm=1000, seed=123,
                            alpha=0.05, between_min_trials=5):
    """
    Fit within-block adaptation time constants (tau) per subject per block, using
    the same pipeline and eligibility criteria as the Figure04_RRvsBound tau insets
    (panels D-F): block 1 eligibility is within-block adaptation significance;
    blocks 2+ eligibility is significant change vs. the immediately preceding block.

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table.
    blocks : tuple or list of int
        Block indices to fit, in order. Default (1, 2, 3).
    max_trial : int
        Number of trial-number x-values to compute each curve over, and the
        tau-fit window / censoring boundary. Default 40.
    half_win, min_win : int
        Smoothing-window half-width and minimum trial count, passed to
        compute_per_subject_curves_with_nulls. Defaults 3, 3.
    n_perm : int
        Number of permutation nulls per subject/block. Default 1000.
    seed : int
        Seed for the permutation RNG. Default 123.
    alpha : float
        Significance threshold for both eligibility tests. Default 0.05.
    between_min_trials : int
        Minimum trials per compared block for the between-block eligibility
        test (blocks 2+). Default 5.

    Returns
    -------
    dict with keys:
      subjects    : list of subject indices (row order of all per-subject arrays)
      trial_nums  : (max_trial,) int array
      real_curves : (n_subjects, max_trial, n_blocks) smoothed z-scored |bound| curves
      sig_tau     : (n_subjects, n_blocks) bool -- tau-fit eligibility. Block 0's
                    within-block test already implies curve data exists (NaN
                    p-value -> not significant); blocks 1+ additionally require
                    curve data explicitly, since between_block_significance uses
                    a separate, looser trial-count filter that can mark a subject
                    "significant" without them having enough local trial density
                    for compute_per_subject_curves_with_nulls to produce a
                    finite curve point anywhere in the block.
      taus        : (n_subjects, n_blocks) float -- fitted tau, NaN if ineligible/failed
      censored    : (n_subjects, n_blocks) bool -- True if fit hit max_trial (not a
                    real measurement, excluded from "good" fits)
      good_tau    : pd.DataFrame, index=subjects, columns=list(blocks) -- fitted tau
                    where the fit is "good" (eligible, converged, tau < max_trial),
                    NaN everywhere else. This is the table to use for gating trials
                    on a subject's own adaptation time constant.
    """
    blocks = list(blocks)
    trial_nums, real_curves, perm_curves, subjects = compute_per_subject_curves_with_nulls(
        data_table, max_trial, blocks, half_win=half_win, min_win=min_win,
        n_perm=n_perm, seed=seed)

    _, sig_within = per_subject_significance(real_curves, perm_curves, alpha=alpha)
    _, sig_between = between_block_significance(
        data_table, blocks, alpha=alpha, min_trials=between_min_trials)

    # lhas_curve: does this subject/block have at least one finite curve point to
    # fit at all? Block 0's sig_within is already implicitly gated by this (see
    # per_subject_significance), but sig_between is computed independently with
    # its own, looser trial-count filter and needs the same gate applied here.
    lhas_curve = np.any(np.isfinite(real_curves), axis=1)
    sig_tau = sig_within.copy()
    sig_tau[:, 1:] = sig_between[:, 1:] & lhas_curve[:, 1:]

    taus = np.full((len(subjects), len(blocks)), np.nan)
    lcensored = np.zeros((len(subjects), len(blocks)), dtype=bool)
    for bi in range(len(blocks)):
        for si in range(len(subjects)):
            if sig_tau[si, bi]:
                tau, cens = fit_exp_tau(trial_nums, real_curves[si, :, bi], tau_max=float(max_trial))
                taus[si, bi] = tau
                lcensored[si, bi] = cens

    lgood = np.isfinite(taus) & ~lcensored
    good_tau = pd.DataFrame(
        np.where(lgood, taus, np.nan), index=subjects, columns=blocks)

    return dict(subjects=subjects, trial_nums=trial_nums, real_curves=real_curves,
                sig_tau=sig_tau, taus=taus, censored=lcensored, good_tau=good_tau)


def get_tau_exclusion_mask(data_table, good_tau):
    """
    Keep-mask that drops each subject's adaptation transient at the start of a block.

    The convention used by Figure03S04 / Figure03S05 / Figure03S06 (their local
    ``tau_exclusion_mask`` / ``make_tau_exclusion_mask``): for a subject with a
    good tau fit in a block, trials with ``trial_number < ceil(tau)`` are
    dropped; subjects without a good fit (ineligible, failed, or censored) keep
    all their trials. Applied on top of the standard quality filters.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials with ``subject_index``, ``block_index`` and ``trial_number``.
    good_tau : pd.DataFrame
        ``get_adaptation_tau_fits(...)['good_tau']`` (index subjects, columns
        blocks; NaN where there is no good fit).

    Returns
    -------
    pd.Series of bool, same index as data_table (True = keep).
    """
    tau_long = good_tau.stack().rename("tau")
    tau_long.index.names = ["subject_index", "block_index"]
    key = pd.MultiIndex.from_arrays([data_table["subject_index"], data_table["block_index"]])
    tau = tau_long.reindex(key).to_numpy()
    drop = np.isfinite(tau) & (data_table["trial_number"].to_numpy() < np.ceil(np.nan_to_num(tau)))
    return pd.Series(~drop, index=data_table.index)
