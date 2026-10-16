"""
Within-block adaptation time-constant (tau) fits, and trial-to-trial structure of the bound.

The tau fits give the adaptation curves and tau insets of Figure04_RRvsBound
and Figure04S01_RRvsBoundPD, and the adaptation transient that
``pigeon.stopping.get_stopping_model_trials`` drops before every stopping-model
fit (``get_tau_exclusion_mask``).

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

Also ``get_sequential_bound_stats``: per-sequence trial-to-trial structure of
|bound| (regression of the change on the previous value, SD, lag-1
autocorrelation), and ``get_post_error_bound_effect``: the change in |bound|
after an error, controlling for the previous trial's |bound|; both used by the
Figure 3 supplement on sequential structure.
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
                                           n_perm=1000, seed=123,
                                           value_col='abs_bound', zscore=True):
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
    value_col : str
        Per-trial quantity to average. Default 'abs_bound'; e.g. a residual
        from the stopping model (``pigeon.stopping.get_bound_residuals``) or
        a guess probability. Trials with a non-finite value are skipped.
    zscore : bool
        z-score the values within each subject x block before smoothing
        (default). False keeps their units (e.g. a log ratio, whose
        steady-state value is already ~0).

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
            sd = sd[np.isfinite(sd[value_col].to_numpy(float))]
            if sd.shape[0] < 2:
                continue
            if zscore:
                mu = sd[value_col].mean()
                sigma = sd[value_col].std()
                if sigma < 1e-10:
                    continue
                z = (sd[value_col].to_numpy(float) - mu) / sigma
            else:
                z = sd[value_col].to_numpy(float)
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
    block[i] (i = 1 .. len(blocks)-1): an unpaired, two-sided Mann-Whitney U test on
    the trials passing get_good_trial_array's default filter (DT >= 2,
    trial_number >= 10, no wall hit, RT cutoff).

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
                            alpha=0.05, between_min_trials=5,
                            value_col='abs_bound', zscore=True):
    """
    Fit within-block adaptation time constants (tau) per subject per block.

    Block 1 eligibility is within-block adaptation significance (the subject's
    curve vs. its permutation null); blocks 2+ eligibility is a significant change
    of steady-state |bound| from the immediately preceding block.

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
    value_col, zscore
        Passed to compute_per_subject_curves_with_nulls (the curves that are
        tested and fit). The between-block eligibility test always uses
        ``abs_bound``: it asks whether the steady-state bound changed between
        blocks, which a within-block residual (~0 at steady state in every
        block by construction) cannot answer.

    Returns
    -------
    dict with keys:
      subjects    : list of subject indices (row order of all per-subject arrays)
      trial_nums  : (max_trial,) int array
      real_curves : (n_subjects, max_trial, n_blocks) smoothed (z-scored) value_col curves
      perm_curves : (n_perm, n_subjects, max_trial, n_blocks) trial-order permutation
                    nulls of real_curves (for group_null_band)
      sig_within  : (n_subjects, n_blocks) bool -- within-block adaptation (curve vs.
                    its permutation null), every block
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
        n_perm=n_perm, seed=seed, value_col=value_col, zscore=zscore)

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

    return dict(subjects=subjects, trial_nums=trial_nums, real_curves=real_curves, perm_curves=perm_curves,
                sig_within=sig_within, sig_tau=sig_tau, taus=taus, censored=lcensored, good_tau=good_tau)


def get_tau_exclusion_mask(data_table, good_tau):
    """
    Keep-mask that drops each subject's adaptation transient at the start of a block.

    For a subject with a good tau fit in a block, trials with
    ``trial_number < ceil(tau)`` are dropped; subjects without a good fit
    (ineligible, failed, or censored) keep all their trials.

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


def get_sequential_bound_stats(data_table, group_cols=("subject_index", "block_index"), value_col="abs_bound",
                               min_trials=20):
    """
    Trial-to-trial structure of the bound within each sequence of trials.

    For each group (by default one subject's block), trials are ordered by
    ``trial_number`` and three statistics of the value sequence are computed:

    - ``delta_slope``: slope of the regression of the change from one trial to
      the next on the earlier trial's value (-1 = independent draws around a
      constant mean, i.e. pure regression to the mean; values above -1 mean
      the value carries over to the next trial);
    - ``sd``: standard deviation of the values (ddof = 1);
    - ``lag1_r``: Pearson correlation between consecutive values.

    Trial selection is the caller's job (pass only the trials to use, in any
    order); rows with a non-finite value are dropped, and groups with fewer
    than ``min_trials`` remaining trials get NaN statistics.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials with ``trial_number``, ``value_col`` and ``group_cols``.
    group_cols : sequence of str
        Columns defining one sequence (e.g. add ``'rep'`` for simulated
        repetitions).
    value_col : str
    min_trials : int

    Returns
    -------
    pd.DataFrame indexed by ``group_cols`` with ``n_trials``, ``delta_slope``,
    ``sd``, ``lag1_r``.
    """
    rows = {}
    for key, g in data_table.groupby(list(group_cols)):
        v = g.sort_values("trial_number")[value_col].to_numpy(float)
        v = v[np.isfinite(v)]
        stats = {"n_trials": len(v), "delta_slope": np.nan, "sd": np.nan, "lag1_r": np.nan}
        if len(v) >= min_trials and np.ptp(v[:-1]) > 0 and np.ptp(v[1:]) > 0:
            prev, nxt = v[:-1], v[1:]
            stats["delta_slope"] = scipy.stats.linregress(prev, nxt - prev).slope
            stats["sd"] = np.std(v, ddof=1)
            stats["lag1_r"] = np.corrcoef(prev, nxt)[0, 1]
        rows[key] = stats
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index = pd.MultiIndex.from_tuples(out.index, names=list(group_cols)) if len(group_cols) > 1 \
        else pd.Index(out.index, name=group_cols[0])
    return out


def get_post_error_bound_effect(data_table, group_cols=("subject_index", "block_index"), value_col="abs_bound",
                                min_post_error=3, min_trials=10):
    """
    Relative change in the bound on the trial after an error.

    Within each group (by default one subject's block), trials are ordered by
    ``trial_number`` and the value is divided by the group's median, so effects
    are fractions of the subject's typical bound. For every trial n with a
    finite value whose immediately preceding trial (trial_number n - 1) is in
    the table, the least-squares regression

        value(n) / median = b0 + b_error * error(n-1) + b_prev * prev(n-1)

    is fit, where ``error`` = 1 - ``correct`` of the previous trial and ``prev``
    is the previous trial's relative value minus its group mean. When the
    previous trial has no finite value (e.g. a one-step guess, whose bound
    cannot be measured), ``prev`` is set to 0, i.e. the mean is imputed; the
    regressor is there so that carryover of the bound (errors are more common
    after low bounds) is not counted as a post-error effect.

    Pass every trial of each sequence (so that previous trials are found), with
    ``value_col`` set to NaN on trials that should not serve as trial n.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials with ``trial_number``, ``correct``, ``value_col`` and
        ``group_cols``.
    group_cols : sequence of str
        Columns defining one sequence (add ``'rep'`` for simulated repetitions).
    value_col : str
    min_post_error : int
        Groups with fewer usable post-error trials get NaN coefficients.
    min_trials : int
        Groups with fewer usable trials in all get NaN coefficients.

    Returns
    -------
    pd.DataFrame indexed by ``group_cols`` with ``n_trials``, ``n_post_error``,
    ``n_prev_imputed``, ``post_error_effect`` (b_error) and ``prev_coef``
    (b_prev).
    """
    rows = {}
    for key, g in data_table.groupby(list(group_cols)):
        g = g.sort_values("trial_number")
        v = g[value_col].to_numpy(float)
        v = v / np.nanmedian(v) if np.isfinite(v).any() else v
        tn = g["trial_number"].to_numpy()
        lprev = np.r_[False, np.diff(tn) == 1]
        prev_v = np.r_[np.nan, v[:-1]]
        prev_err = np.r_[np.nan, 1.0 - g["correct"].to_numpy(float)[:-1]]
        lu = lprev & np.isfinite(v) & np.isfinite(prev_err)
        prev_c = prev_v[lu] - np.nanmean(prev_v[lu]) if np.isfinite(prev_v[lu]).any() else prev_v[lu]
        limp = ~np.isfinite(prev_c)
        prev_c[limp] = 0.0
        err = prev_err[lu]
        stats = {"n_trials": int(lu.sum()), "n_post_error": int(err.sum()), "n_prev_imputed": int(limp.sum()),
                 "post_error_effect": np.nan, "prev_coef": np.nan}
        if stats["n_trials"] >= min_trials and stats["n_post_error"] >= min_post_error \
                and stats["n_post_error"] < stats["n_trials"]:
            X = np.column_stack([np.ones(len(err)), err, prev_c])
            b = np.linalg.lstsq(X, v[lu], rcond=None)[0]
            stats["post_error_effect"], stats["prev_coef"] = b[1], b[2]
        rows[key] = stats
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index = pd.MultiIndex.from_tuples(out.index, names=list(group_cols)) if len(group_cols) > 1 \
        else pd.Index(out.index, name=group_cols[0])
    return out
