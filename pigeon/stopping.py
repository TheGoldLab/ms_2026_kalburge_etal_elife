"""
Trial-level stopping model: variable, time-varying bound with sensory noise,
plus guesses, anticipations, and choice lapses.

Fits *when* a subject commits and *which* side they choose from the pigeon's
full on-screen path on every trial, instead of inferring one bound per trial
and filtering out the trials that don't fit (DT cutoffs). Used by
notebooks/Test_stoppingModel.ipynb.

Generative model (per trial)
----------------------------
Positions ``x_0 = 0, x_1, x_2, ...`` are the pigeon's on-screen positions (the
``steps`` column of ``get_data_table``; clamped at +/-WALL by the task). Each
position is shown for 200 ms (``UPDATE_INTERVAL`` in the task code).

1. **Anticipation.** With probability ``anticipation_rate`` the key is pressed
   during the trial's first frame (RT = 1), before anything shown could have
   been processed. The choice is random.
2. **Bound.** The bound at step j is ``b_j = m * theta(j)``. The trial's
   multiplier ``m`` is gamma-distributed with mean 1 and coefficient of
   variation ``bound_cv``. The time course ``theta(j)`` is
   ``bound_scale * h(j)``. Default ('knee' form): ``log h`` falls (or rises)
   linearly from ``log_h_start`` at step 1 to 0 at a free, continuous knee
   step, then changes by ``late_slope`` per step, so ``bound_scale`` is the
   mean bound at the knee (the paper's single bound measure). Alternative
   ('knots' form): ``log h`` piecewise linear in j through ``knots``
   (constant outside them) with ``h(anchor) = 1``, so ``bound_scale`` is the
   mean bound at the anchor step (default 6). ``h`` is shared by
   all of a subject's groups (``time_course='shared'``, the default), separate
   per group (``'per_group'``), flat (``'flat'``), or separate per value of
   another column (``time_course_col``, e.g. one shape per SNR while the
   other parameters stay per block). On change-point trials, positions
   j >= change_point use ``bound_scale_post`` (if fit).
3. **Sensory noise.** The subject sees ``y_j = x_j + e_j`` with independent
   ``e_j ~ N(0, sensory_std^2)``, and commits at the first j >= 1 with
   ``|y_j| >= b_j``, choosing the side crossed. ``sensory_std = 0`` gives exact
   crossings of the on-screen position.
4. **Guess.** If the bound isn't crossed at step j, the subject commits anyway
   with probability ``guess_rate`` (regardless of the evidence), choosing the
   side of the perceived position ``y_j``. This includes step 0, the start frame
   (pigeon at center, so the choice is random; RT = NDT + 1).
   Optionally (``guess_time_course``) the guess rate varies over the trial:
   ``expit(logit(guess_rate) + log_g(j))``, with ``log_g`` piecewise linear
   through the same knots as ``log h`` and 0 at the anchor, so ``guess_rate``
   is the rate at the anchor step. This is the alternative to a collapsing
   bound for time-dependent stopping (e.g. more guessing early in the trial).
5. **Lapse.** With probability ``lapse_rate`` the choice is random instead.
6. **NDT.** The response comes NDT + 1 frames after the commit step,
   ``RT = k + NDT + 1`` (the ``DT = RT - NDT - 1`` convention of
   ``get_bounds``). Default support NDT in {1, 2}: 200-400 / 400-600 ms from the
   commit position appearing to the key press; longer delays are not
   physiologically plausible as a sensorimotor latency.

Likelihood
----------
Given m, steps are independent: with ``q_j = P(|y_j| < b_j)`` and up/down
crossing probabilities ``r_j^+ = P(y_j >= b_j)``, ``r_j^- = P(y_j <= -b_j)``, the
probability of no commit through step k is
``S_k = (1 - anticipation_rate) * prod_{j=1..k} q_j (1 - guess_rate_j)``, and
P(commit at k, right) = ``S_{k-1} [r_k^+ + guess_rate_k P(0 < y_k < b_k)]``
(left analogously): a guess happens only when the bound isn't crossed, so its
side is that of a perceived position inside the bound. The integral over m is restricted, per trial, to the
window where the integrand varies (see ``_trial_likelihood_padded``); outside
it the integrand is ~0 (bound crossed earlier) or constant (only guesses can
commit). Lapses mix the choice with 1/2; each trial's likelihood
averages over NDT.

**Wall-hit trials.** Once the pigeon reaches the wall (first step w with
|x_w| >= WALL) it stays at the edge until the key press, so a long RT after
that carries no information about stopping. A wall trial whose response came
later than any NDT allows (RT > w + max(ndt_values) + 1) contributes
``S_{w-1}`` (no commit before the wall) times the choice probability at the
wall; wall trials answered within that window use the ordinary likelihood.
(Censoring per NDT value instead lets the censored mass compete with point
probabilities and biases NDT and the bound upward.)

Fitting
-------
``fit_stopping_model`` maximizes the penalized likelihood over all trials of
one subject with L-BFGS-B on transformed scales. By default ``bound_scale``,
``bound_cv``, ``guess_rate``, ``lapse_rate``, ``anticipation_rate`` (and any
``post_params``) are per group, and the bound's time-course shape,
``sensory_std`` and the NDT probabilities are shared by the subject's groups
(the split chosen by model comparison on OL/MX; see
notebooks/Test_stoppingModel.ipynb); ``shared_params`` and ``time_course``
change that. A penalty on adjacent differences of ``log h``
(``smooth_penalty``; Gaussian prior SD ``1/sqrt(2 * smooth_penalty)`` on each
log change, 0.5 by default) keeps the time course near flat unless the data
say otherwise: with ~50-150 trials per block, an unpenalized per-block curve
trades an extreme early bound against a steep collapse.

Units: ``bound_scale`` and ``sensory_std`` are in position units on *raw*
positions (no bias correction; the likelihood accounts for overshoot).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.optimize
import scipy.special
import scipy.stats

from .data import WALL, apply_bias_corrections, get_bounds, get_data_table, get_good_trial_array

NDT_VALUES = (1, 2)
KNOTS = (1, 6, 16)
ANCHOR = 6   # knot where h = 1, so bound_scale is the mean bound there
GROUP_PARAMS = ("bound_scale", "bound_cv", "guess_rate", "lapse_rate", "anticipation_rate")
POST_PARAMS = ("bound_scale", "guess_rate")
SHARED_PARAMS = ()   # default: every per-group parameter is separate per group
TIME_COURSES = ("flat", "shared", "per_group")
TIME_COURSE_FORMS = ("knots", "knee")
KNEE_PARAMS = ("log_h_start", "knee", "late_slope")

# Optimizer limits on the transformed scales.
_LOG_POS_LIMITS = (np.log(0.002), np.log(2.0))
_LOG_CV_LIMITS = (np.log(0.03), np.log(2.0))
_LOG_SENSORY_LIMITS = (np.log(1e-3), np.log(1.0))
_LOGIT_LIMITS = (-14.0, 8.5)
_NDT_LOGIT_LIMITS = (-10.0, 10.0)
_LOG_H_LIMITS = (-3.0, 3.0)
_LOG_G_LIMITS = (-6.0, 6.0)   # logit-scale shift of the guess rate
_KNEE_LIMITS = (1.5, 15.0)    # step of the knee (continuous)
_LATE_SLOPE_LIMITS = (-0.15, 0.15)   # change in log h per step after the knee
_MIN_LIK = 1e-300
_TINY = 1e-300


def _gamma_ppf(u, cv):
    """Quantiles of a mean-1 gamma with coefficient of variation cv (broadcastable)."""
    shape = 1.0 / np.asarray(cv, float) ** 2
    return scipy.stats.gamma.ppf(u, a=shape, scale=1.0 / shape)


def _log_h(log_h_knots, knots, num_steps):
    """(..., num_steps) log time course: piecewise linear in step through the knots."""
    j = np.arange(num_steps)
    log_h_knots = np.atleast_2d(log_h_knots)
    return np.stack([np.interp(j, knots, row) for row in log_h_knots])


def _knee_log_h(log_h_start, knee, late_slope, steps):
    """
    (n_shapes, len(steps)) log time course of the knee form.

    Linear in step from ``log_h_start`` at step 1 to 0 at ``knee``, then
    ``late_slope`` per step; steps before 1 take the step-1 value.
    """
    a, k, sl = (np.atleast_1d(np.asarray(v, float))[:, None] for v in (log_h_start, knee, late_slope))
    j = np.maximum(np.asarray(steps, float)[None, :], 1.0)
    return np.where(j < k, a * (k - j) / (k - 1.0), sl * (j - k))


def get_log_h(fits, steps, knots=KNOTS):
    """
    Fitted log bound time course, log h(j), for each row of a fit table.

    Handles both forms: the knee form (``log_h_start``, ``knee``,
    ``late_slope`` columns) and the knots form (``log_h_k<knot>`` columns;
    missing columns mean flat).

    Parameters
    ----------
    fits : pd.DataFrame or pd.Series
        Rows of fit_stopping_model(s) output.
    steps : array-like of int
    knots : sequence of int
        Knots of the knots form.

    Returns
    -------
    (n_rows, len(steps)) array.
    """
    f = fits.to_frame().T if isinstance(fits, pd.Series) else fits
    steps = np.asarray(steps, float)
    out = np.zeros((len(f), len(steps)))
    lk = np.isfinite(f["knee"].to_numpy(float)) if "knee" in f else np.zeros(len(f), bool)
    if lk.any():
        out[lk] = _knee_log_h(*(f.loc[lk, c].to_numpy(float) for c in KNEE_PARAMS), steps)
    if (~lk).any():
        lh = np.stack([f[f"log_h_k{k}"].to_numpy(float) if f"log_h_k{k}" in f else np.zeros(len(f))
                       for k in knots], axis=1)[~lk]
        out[~lk] = np.stack([np.interp(steps, knots, np.nan_to_num(row)) for row in lh])
    return out


def _shift_logit(rate, shift):
    """expit(logit(rate) + shift), keeping rate = 0 at 0 (the guess-rate time course)."""
    with np.errstate(divide="ignore"):
        return scipy.special.expit(scipy.special.logit(rate) + shift)


def get_commit_hazard_table(data_table, ndt=1, wall=WALL):
    """
    Step-by-step risk set for a model-free commit hazard.

    For each trial, the commit step is taken as ``k = RT - ndt - 1`` (the
    ``DT`` convention of ``get_bounds`` with a fixed NDT). Every step
    ``j = 1..k`` at which the subject had not yet committed contributes one
    row: the pigeon's distance from center ``|x_j|`` and whether the commit
    happened at that step. Steps at or after the pigeon first reached the
    wall are left out (a position held at the wall carries no new
    information), as are RT = 1 trials (key pressed on the first frame) and
    trials with ``k < 1``. Averaging ``commit`` within (step, |x|) bins gives
    P(commit at step j | |x_j|, not committed before j). Apply the same
    function to real and simulated trials so both share the convention.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials with ``steps``, ``RT``, and any grouping columns to carry
        (``subject_index``, ``condition`` if present).
    ndt : int
        NDT (steps) used to place the commit.
    wall : float
        Screen-edge position.

    Returns
    -------
    pd.DataFrame with ``trial`` (index label in data_table), ``step``,
    ``abs_x``, ``commit`` (bool), plus ``subject_index`` and ``condition``
    when present in data_table.
    """
    keep = [c for c in ("subject_index", "condition") if c in data_table]
    parts = []
    for idx, steps, rt in zip(data_table.index, data_table["steps"], data_table["RT"]):
        rt = int(rt)
        k = rt - ndt - 1
        if rt == 1 or k < 1:
            continue
        x = np.abs(np.asarray(steps, float))
        at_wall = np.nonzero(x >= wall - 1e-9)[0]
        last = min(k, at_wall[0] - 1 if len(at_wall) else k)
        if last < 1:
            continue
        j = np.arange(1, last + 1)
        parts.append(pd.DataFrame({"trial": idx, "step": j, "abs_x": x[j], "commit": j == k}))
    if not parts:
        return pd.DataFrame(columns=["trial", "step", "abs_x", "commit"] + keep)
    out = pd.concat(parts, ignore_index=True)
    for c in keep:
        out[c] = data_table.loc[out["trial"], c].to_numpy()
    return out


COMMIT_SOURCES = ("guess", "lapse", "timing", "sensory noise", "measurement", "collapsing bound")


def get_commit_sources(sim_table):
    """
    Which model mechanism produced each simulated trial's commitment and choice.

    For trials simulated by simulate_stopping_trials and run through the
    real-data bound pipeline (infer_bounds_like_data), each trial gets the
    first matching source, in this order:

    1. ``'guess'``: the commit was a guess (including start-frame guesses) or
       an anticipation, not a bound crossing;
    2. ``'lapse'``: the choice was random (lapse);
    3. ``'timing'``: the pipeline placed the commit at the wrong step
       (inferred ``DT`` differs from the true ``commit_step``, i.e. the
       NDT assumed by get_bounds was not the one that occurred);
    4. ``'sensory noise'``: a bound commit triggered by the perceived position
       while the on-screen position had not reached the bound on that side
       (``true_crossed`` False);
    5. ``'measurement'``: the pigeon crossed zero between steps ``DT - 1``
       and ``DT``, so the midpoint used by get_bounds and
       get_crossing_diagnostics can fall on the other side from the position
       at the commit;
    6. ``'collapsing bound'``: none of the above. Applied to premature
       crossings, these are trials where the pigeon had been farther out at
       an earlier step, when the falling bound was still higher, than where
       the subject committed.

    Parameters
    ----------
    sim_table : pd.DataFrame
        Simulated trials with ``steps``, ``commit_type``, ``lapse``,
        ``true_crossed``, ``commit_step`` and the pipeline's ``DT``.

    Returns
    -------
    pd.Series of labels from COMMIT_SOURCES (index of sim_table).
    """
    t = sim_table

    def _zero_crossing(steps, dt):
        dt = int(dt) if np.isfinite(dt) else -1
        return 1 <= dt < len(steps) and np.sign(steps[dt - 1]) * np.sign(steps[dt]) < 0

    zero_cross = np.array([_zero_crossing(np.asarray(st, float), dt) for st, dt in zip(t["steps"], t["DT"])])
    src = np.select([t["commit_type"].isin(["guess", "anticipation"]).to_numpy(), t["lapse"].to_numpy(bool),
                     (t["DT"] != t["commit_step"]).to_numpy(), ~t["true_crossed"].to_numpy(bool), zero_cross],
                    list(COMMIT_SOURCES[:5]), COMMIT_SOURCES[5])
    return pd.Series(src, index=t.index, name="source")


def get_plateau_at_limit(fits, rtol=0.02):
    """
    Flag fits whose bound plateau sits at a fit limit (no evidence-based stopping).

    ``bound_scale`` is bounded to [0.002, 2.0] during fitting. At the upper
    limit the bound is never what triggers a commit (the subject responds
    essentially at random: high guess and lapse rates); at the lower limit
    any movement triggers one. Either way the plateau is not a bound
    estimate, and figures exclude these subject-blocks from statistics (with
    counts reported).

    Parameters
    ----------
    fits : pd.DataFrame
        Output of fit_stopping_models (``bound_scale`` column).
    rtol : float
        Relative distance from a limit that counts as at the limit.

    Returns
    -------
    pd.Series of bool (index of fits); NaN plateaus are False.
    """
    lo, hi = np.exp(_LOG_POS_LIMITS)
    b = fits["bound_scale"]
    return (b <= lo * (1 + rtol)) | (b >= hi * (1 - rtol))


def bound_time_course(fit_row, steps, knots=KNOTS, post=False):
    """
    Mean bound at each step for one fitted group.

    Parameters
    ----------
    fit_row : mapping
        A row of fit_stopping_model's ``params`` table (or fit_stopping_models'
        output), with ``bound_scale`` and the time-course entries (see get_log_h).
    steps : array-like of int
        Steps at which to evaluate theta(j).
    knots : sequence of int
    post : bool
        Use ``bound_scale_post`` instead of ``bound_scale``.

    Returns
    -------
    np.ndarray of mean bounds (position units).
    """
    scale = fit_row["bound_scale_post" if post else "bound_scale"]
    return scale * np.exp(get_log_h(pd.Series(fit_row), steps, knots)[0])


def get_effective_bounds(data_table, fits, group_col="condition", knots=KNOTS, ndt_values=NDT_VALUES):
    """
    Fitted mean bound at each trial's commit step, averaged over the fitted NDT.

    For a trial with response time RT the commit step is ``RT - ndt - 1``
    (clipped to >= 1); the result is ``sum_ndt P(ndt) * theta(RT - ndt - 1)``.
    Averaged over a subject's trials this is the model's counterpart of a
    mean measured bound: it weights the time course by when that subject
    actually responded.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials with ``subject_index``, ``group_col`` and ``RT``.
    fits : pd.DataFrame
        Output of fit_stopping_models (``group`` matches ``group_col``).
    group_col : str
    knots, ndt_values : sequences
        Must match the fits.

    Returns
    -------
    pd.Series (index of data_table); NaN for trials without a fit.
    """
    tc_cols = [c for c in fits.columns if c.startswith("log_h_k") or c in KNEE_PARAMS]
    cols = ["bound_scale"] + tc_cols + [f"ndt_p{n}" for n in ndt_values]
    f = data_table[["subject_index", group_col, "RT"]].merge(
        fits[["subject_index", "group"] + cols], left_on=["subject_index", group_col],
        right_on=["subject_index", "group"], how="left")
    max_step = int(np.nanmax(f["RT"])) + 1
    log_h = get_log_h(f, np.arange(max_step), knots)          # (n_trials, max_step)
    rows = np.arange(len(f))
    out = np.zeros(len(f))
    for ndt in ndt_values:
        j = np.clip(f["RT"].to_numpy(int) - ndt - 1, 1, None)
        out += f[f"ndt_p{ndt}"].to_numpy() * f["bound_scale"].to_numpy() * np.exp(log_h[rows, j])
    return pd.Series(out, index=data_table.index)


def get_fit_vs_median_bounds(data_table, fits, bias_file, group_col="condition", knots=KNOTS,
                             ndt_values=NDT_VALUES):
    """
    Per subject x group: fitted bounds next to the paper's median |bound|.

    The median |bound| uses the paper's standard trial set
    (``get_good_trial_array``: DT >= 2, trial_number >= 10, no wall hit, RT
    cutoff; plus a finite, nonzero bound), on raw positions and after
    ``apply_bias_corrections``. The fitted bound is the mean of
    ``get_effective_bounds`` over the same trials, plus ``bound_scale`` (the
    bound plateau: the mean bound at the knee, or at the anchor step for the
    knots form).

    Parameters
    ----------
    data_table : pd.DataFrame
        get_data_table(..., correct_bias=None) output (or infer_bounds_like_data
        output for simulated trials), with ``group_col``.
    fits : pd.DataFrame
        Output of fit_stopping_models.
    bias_file : str or Path
        Calibration file for apply_bias_corrections.
    group_col, knots, ndt_values
        As in get_effective_bounds.

    Returns
    -------
    pd.DataFrame with ``subject_index``, ``group``, ``n_trials``, ``median_raw``,
    ``median_corrected``, ``bound_scale``, ``effective_bound``.
    """
    lg = get_good_trial_array(data_table) & np.isfinite(data_table["bound"]) & (data_table["bound"] != 0)
    d = data_table[lg].copy()
    d["abs_bound_corrected"] = apply_bias_corrections(d, str(bias_file))["abs_bound"]
    d["effective_bound"] = get_effective_bounds(d, fits, group_col, knots, ndt_values)
    d["abs_bound"] = d["bound"].abs()
    g = d.groupby(["subject_index", group_col])
    out = pd.DataFrame({"n_trials": g.size(),
                        "median_raw": g.abs_bound.median(),
                        "median_corrected": g.abs_bound_corrected.median(),
                        "effective_bound": g.effective_bound.mean()}).reset_index()
    out = out.rename(columns={group_col: "group"})
    return out.merge(fits[["subject_index", "group", "bound_scale"]], on=["subject_index", "group"], how="left")


def _pad_steps(steps_list):
    """Stack variable-length position sequences into an (n, max_len) NaN-padded array."""
    lens = np.array([np.sum(np.isfinite(np.asarray(s, float))) for s in steps_list])
    x = np.full((len(steps_list), int(lens.max())), np.nan)
    for tt, s in enumerate(steps_list):
        s = np.asarray(s, float)
        s = s[np.isfinite(s)]
        x[tt, : len(s)] = s
    return x, lens


def _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, p, knots, ndt_values, ndt_probs,
                      n_quad=24, wall=WALL, n_buckets=4, return_parts=False, shape_idx=None):
    """
    Per-trial likelihood, computed in length buckets.

    Trials range from 1 to ~50 steps, so a single NaN-padded (n, L, n_quad)
    array is mostly padding; sorting trials by length and padding each bucket
    only to its own maximum gives the same result much faster. With
    ``return_parts``, also returns the parts of each likelihood from guesses
    and from wall censoring (see _trial_likelihood_padded).
    """
    order = np.argsort(lens, kind="stable")
    out = np.empty((3, len(lens)))
    for idx in np.array_split(order, min(n_buckets, len(order))):
        if idx.size == 0:
            continue
        L = int(lens[idx].max())
        out[:, idx] = _trial_likelihood_padded(
            x[idx, :L], lens[idx], choice_pm[idx], group_idx[idx], post_mask[idx, :L], p, knots,
            ndt_values, ndt_probs, n_quad=n_quad, wall=wall, return_parts=True,
            shape_idx=None if shape_idx is None else shape_idx[idx])
    return out if return_parts else out[0]


def _trial_likelihood_padded(x, lens, choice_pm, group_idx, post_mask, p, knots, ndt_values, ndt_probs,
                             n_quad=24, wall=WALL, return_parts=False, shape_idx=None):
    """
    Per-trial likelihood of (RT, choice) under the stopping model.

    Parameters
    ----------
    x : (n, L) array
        On-screen positions, NaN-padded; ``x[:, 0] = 0``.
    lens : (n,) int array
        Number of recorded positions per trial (= RT).
    choice_pm : (n,) array
        Choices coded -1 (left) / +1 (right).
    group_idx : (n,) int array
        Index into the per-group parameter arrays.
    post_mask : (n, L) bool array
        True for positions governed by the post-change-point parameters.
    p : dict
        Natural-scale parameters: per-group arrays for GROUP_PARAMS and
        ``<name>_post`` for POST_PARAMS, ``log_h`` of shape (n_shapes, len(knots))
        with n_shapes 1 or n_groups, scalar ``sensory_std``.
    knots, ndt_values, ndt_probs, n_quad, wall
        See module docstring.
    shape_idx : (n,) int array or None
        Index into the time-course shapes per trial (fit_stopping_model's
        ``time_course_col``); None = shape per group if there are several,
        else the single shape.

    Returns
    -------
    (n,) array of likelihoods; with ``return_parts``, a (3, n) array of the
    likelihood, its part from guess commits (including start-frame guesses
    and anticipations), and its part from wall-censored trials (commit type
    unknown).

    Notes
    -----
    The integral over the bound multiplier m is split per trial (and per
    target step k). Below ``a = max_{j<k} (|x_j| - 5 sd) / theta_j`` the bound
    was almost surely crossed earlier, so the integrand is ~0. Above
    ``c = max_{j<=k} (|x_j| + 5 sd) / theta_j`` the bound was almost surely
    never reached, so only guesses commit and the integrand is constant (closed
    form). Only [a, c] needs quadrature: ``n_quad`` Gauss-Legendre nodes in the
    gamma CDF scale (24 nodes: within ~0.15 log-likelihood units of a 128-node
    reference over 1500 trials at any sensory_std). With sd = 0 this is exact. (Fixed nodes over the whole
    distribution truncate its upper tail and give near-zero likelihood to
    trials where the pigeon wandered far before committing.)
    """
    n, L = x.shape
    xx = np.nan_to_num(x, nan=0.0)
    ax = np.abs(xx)
    sig = float(p["sensory_std"])
    rows = np.arange(n)

    if "knee" in p:
        log_h = _knee_log_h(p["log_h_start"], p["knee"], p["late_slope"], np.arange(L))
    else:
        log_h = _log_h(p["log_h"], knots, L)
    if shape_idx is None:
        shape_idx = group_idx if log_h.shape[0] > 1 else np.zeros(n, int)
    scale = np.where(post_mask, np.asarray(p["bound_scale_post"])[group_idx][:, None],
                     np.asarray(p["bound_scale"])[group_idx][:, None])
    theta = scale * np.exp(log_h[shape_idx])                                  # (n, L)
    kappa = (1.0 / np.asarray(p["bound_cv"], float) ** 2)[group_idx]           # gamma shape, mean 1

    gr = np.where(post_mask, np.asarray(p["guess_rate_post"])[group_idx][:, None],
                  np.asarray(p["guess_rate"])[group_idx][:, None])
    log_g = _log_h(p.get("log_g", np.zeros((1, len(knots)))), knots, L)
    if np.any(log_g != 0):
        gshape_idx = group_idx if log_g.shape[0] > 1 else np.zeros(n, int)
        gr = _shift_logit(gr, log_g[gshape_idx])
    lapse = np.asarray(p["lapse_rate"])[group_idx]
    antic = np.asarray(p["anticipation_rate"])[group_idx]
    log_guess_surv = np.log1p(-antic)[:, None] + np.cumsum(np.log1p(-gr), axis=1)   # no guess through k
    if sig > 0:
        p_right = scipy.special.ndtr(xx / sig)
        lo, hi = (ax - 5 * sig) / theta, (ax + 5 * sig) / theta
    else:
        p_right = np.where(xx > 0, 1.0, np.where(xx < 0, 0.0, 0.5))
        lo = hi = ax / theta
    lo[:, 0] = hi[:, 0] = 0.0
    run_lo = np.maximum.accumulate(np.maximum(lo, 0.0), axis=1)
    run_hi = np.maximum.accumulate(hi, axis=1)
    gl_x, gl_w = np.polynomial.legendre.leggauss(n_quad)
    nodes, weights = (gl_x + 1) / 2, gl_w / 2          # Gauss-Legendre on [0, 1]

    def integrate(k, commit):
        """Integral over m of S_{k-1} (survive) or S_{k-1} * commit-at-k terms (right, left)."""
        a = run_lo[rows, k - 1]
        c = run_hi[rows, k] if commit else run_hi[rows, k - 1]
        c = np.maximum(c, a)
        ua = scipy.stats.gamma.cdf(a, kappa, scale=1 / kappa)
        uc = scipy.stats.gamma.cdf(c, kappa, scale=1 / kappa)
        u = ua[:, None] + (uc - ua)[:, None] * nodes[None, :]
        m = scipy.stats.gamma.ppf(u, kappa[:, None], scale=1 / kappa[:, None])   # (n, Q)
        kmax = int(k.max())
        b = theta[:, :kmax + 1, None] * m[:, None, :]                          # (n, kmax+1, Q)
        xb = xx[:, :kmax + 1, None]
        if sig > 0:
            up = scipy.special.ndtr((xb - b) / sig)
            dn = scipy.special.ndtr((-b - xb) / sig)
        else:
            up = (xb >= b).astype(float)
            dn = (xb <= -b).astype(float)
        up[:, 0, :] = dn[:, 0, :] = 0.0
        q = np.clip(1.0 - up - dn, 0.0, 1.0)
        log_q = np.cumsum(np.log(np.maximum(q, _TINY)), axis=1)
        s_prev_guess = np.exp(log_guess_surv[rows, k - 1])
        s_prev = s_prev_guess[:, None] * np.exp(log_q[rows, k - 1, :])        # (n, Q)
        width = uc - ua
        if not commit:
            return width * (s_prev @ weights) + (1 - uc) * s_prev_guess
        g_k = gr[rows, k][:, None]
        pr_k = p_right[rows, k][:, None]
        up_k, dn_k = up[rows, k, :], dn[rows, k, :]
        # A guess at k happens only if the bound wasn't crossed there, so its side is that of a
        # perceived position inside the bound: P(0 < y < b) = P(y > 0) - P(y >= b), and likewise left.
        in_r = np.clip(pr_k - up_k, 0.0, None)
        in_l = np.clip(1 - pr_k - dn_k, 0.0, None)
        pr_b = width * ((s_prev * up_k) @ weights)
        pl_b = width * ((s_prev * dn_k) @ weights)
        pr_g = width * ((s_prev * g_k * in_r) @ weights) + (1 - uc) * s_prev_guess * g_k[:, 0] * pr_k[:, 0]
        pl_g = width * ((s_prev * g_k * in_l) @ weights) + (1 - uc) * s_prev_guess * g_k[:, 0] * (1 - pr_k[:, 0])
        return pr_b + pr_g, pl_b + pl_g, pr_g, pl_g

    at_wall = ax >= wall - 1e-9
    wall_step = np.where(at_wall.any(axis=1), at_wall.argmax(axis=1), L)
    lw = lens > wall_step + max(ndt_values) + 1

    lik = np.zeros(n)
    if lw.any():
        w = np.where(lw, wall_step, 1)
        s_wall = integrate(w, commit=False)
        same = np.sign(xx[rows, np.minimum(w, L - 1)]) == choice_pm
        lik[lw] = (s_wall * np.where(same, 1 - lapse / 2, lapse / 2))[lw]

    lik_wall = lik.copy()
    lant = lens == 1                       # first-frame press: anticipation only
    lik[lant] = antic[lant] * 0.5
    lik_guess = np.where(lant, lik, 0.0)
    for ndt, p_ndt in zip(ndt_values, ndt_probs):
        k = lens - ndt - 1
        term = np.zeros(n)
        term_g = np.zeros(n)
        l0 = ~lw & ~lant & (k == 0)          # guess on the start frame (no evidence)
        term[l0] = term_g[l0] = (1 - antic[l0]) * gr[l0, 0] * 0.5
        lk = ~lw & ~lant & (k >= 1)          # k < 0 is impossible for this NDT
        if lk.any():
            kk = np.where(lk, k, 1)
            pr, pl, pr_g, pl_g = integrate(kk, commit=True)
            p_c = np.where(choice_pm > 0, pr, pl)
            term[lk] = ((1 - lapse) * p_c + lapse / 2 * (pr + pl))[lk]
            p_cg = np.where(choice_pm > 0, pr_g, pl_g)
            term_g[lk] = ((1 - lapse) * p_cg + lapse / 2 * (pr_g + pl_g))[lk]
        lik += p_ndt * np.maximum(term, 0.0)
        lik_guess += p_ndt * np.maximum(term_g, 0.0)
    if return_parts:
        return np.stack([lik, lik_guess, lik_wall])
    return lik


class _Layout:
    """Bookkeeping between the transformed parameter vector and named parameters."""

    def __init__(self, n_groups, post_params, n_ndt, time_course, n_knots, fixed, shared_params=(), anchor_idx=0,
                 guess_time_course="flat", time_course_form="knots", n_tc_groups=None):
        self.n_groups, self.n_ndt, self.time_course = n_groups, n_ndt, time_course
        self.knee = time_course_form == "knee" and time_course != "flat"
        self.post_params = tuple(q for q in POST_PARAMS if q in post_params)
        self.fixed = dict(fixed or {})
        self.shared = tuple(q for q in GROUP_PARAMS if q in shared_params)
        self.n_shapes = {"flat": 0, "shared": 1, "per_group": n_groups}[time_course]
        if n_tc_groups is not None:
            self.n_shapes = n_tc_groups
        self.n_gshapes = {"flat": 0, "shared": 1, "per_group": n_groups}[guess_time_course]
        self.n_free_h = n_knots - 1
        self.anchor_idx = anchor_idx
        spec = []   # (name, size, limits)
        G = n_groups
        size = lambda name: 1 if name in self.shared else G  # noqa: E731
        spec += [("bound_scale", size("bound_scale"), _LOG_POS_LIMITS),
                 ("bound_cv", size("bound_cv"), _LOG_CV_LIMITS),
                 ("guess_rate", size("guess_rate"), _LOGIT_LIMITS),
                 ("lapse_rate", size("lapse_rate"), _LOGIT_LIMITS),
                 ("anticipation_rate", size("anticipation_rate"), _LOGIT_LIMITS)]
        for name in self.post_params:
            spec.append((f"{name}_post", G, _LOGIT_LIMITS if name == "guess_rate" else _LOG_POS_LIMITS))
        spec.append(("sensory_std", 1, _LOG_SENSORY_LIMITS))
        spec.append(("ndt_logits", n_ndt - 1, _NDT_LOGIT_LIMITS))
        if self.knee:
            spec += [("log_h_start", self.n_shapes, _LOG_H_LIMITS), ("knee", self.n_shapes, _KNEE_LIMITS),
                     ("late_slope", self.n_shapes, _LATE_SLOPE_LIMITS)]
        else:
            spec.append(("log_h", self.n_shapes * self.n_free_h, _LOG_H_LIMITS))
        spec.append(("log_g", self.n_gshapes * self.n_free_h, _LOG_G_LIMITS))
        self.spec = [s for s in spec if s[0] not in self.fixed and s[1] > 0]

    def limits(self):
        return [lim for _, size, lim in self.spec for _ in range(size)]

    def unpack(self, theta):
        out, i = {}, 0
        for name, size, _ in self.spec:
            out[name] = theta[i:i + size]
            i += size
        p = {}
        for name in GROUP_PARAMS + tuple(f"{q}_post" for q in self.post_params):
            if name in self.fixed:
                p[name] = np.broadcast_to(np.asarray(self.fixed[name], float), (self.n_groups,))
            elif name.startswith(("guess_rate", "lapse_rate", "anticipation_rate")):
                p[name] = np.broadcast_to(scipy.special.expit(out[name]), (self.n_groups,))
            else:
                p[name] = np.broadcast_to(np.exp(out[name]), (self.n_groups,))
        for name in POST_PARAMS:
            p.setdefault(f"{name}_post", p[name])
        p["sensory_std"] = (float(self.fixed["sensory_std"]) if "sensory_std" in self.fixed
                            else float(np.exp(out["sensory_std"][0])))
        logits = np.r_[0.0, out.get("ndt_logits", np.zeros(0))]
        p["ndt_probs"] = np.exp(logits - scipy.special.logsumexp(logits))
        free_h = out.get("log_h", np.zeros(0)).reshape(max(self.n_shapes, 1), -1) \
            if self.n_shapes and not self.knee else np.zeros((1, self.n_free_h))
        p["log_h"] = np.insert(free_h, self.anchor_idx, 0.0, axis=1)
        if self.knee:
            for name in KNEE_PARAMS:
                p[name] = (np.full(self.n_shapes, float(self.fixed[name])) if name in self.fixed
                           else np.asarray(out[name], float))
        free_g = out.get("log_g", np.zeros(0)).reshape(max(self.n_gshapes, 1), -1) \
            if self.n_gshapes else np.zeros((1, self.n_free_h))
        p["log_g"] = np.insert(free_g, self.anchor_idx, 0.0, axis=1)
        return p


def _prepare(data_table, group_col):
    """Arrays the likelihood needs, from a get_data_table-style DataFrame."""
    x, lens = _pad_steps(list(data_table["steps"]))
    choice_pm = data_table["choice"].to_numpy(float) * 2 - 1
    groups = np.asarray(data_table[group_col]) if group_col is not None else np.zeros(len(data_table))
    group_values, group_idx = np.unique(groups, return_inverse=True)
    cp = (data_table["change_point"].fillna(0).to_numpy(float)
          if "change_point" in data_table else np.zeros(len(data_table)))
    post_mask = (cp[:, None] > 0) & (np.arange(x.shape[1])[None, :] >= cp[:, None])
    return x, lens, choice_pm, group_values, group_idx, post_mask


def stopping_model_nll(data_table, params, group_col="block_index", knots=KNOTS,
                       ndt_values=NDT_VALUES, n_quad=24, wall=WALL):
    """
    Negative log-likelihood of a data table under given stopping-model parameters.

    Parameters
    ----------
    data_table : pd.DataFrame
        get_data_table-style rows (``steps``, ``choice``, optionally
        ``change_point`` and ``group_col``).
    params : dict
        Natural-scale parameters: GROUP_PARAMS (scalar or one per group, in
        sorted group order), optional ``<name>_post``, ``sensory_std``,
        ``ndt_probs`` (one per ndt value), optional ``log_h`` (values at the
        knots, 0 at the anchor; shape (len(knots),) or (n_groups, len(knots));
        default flat), optional ``log_g`` (guess-rate time course, same shape;
        default flat). For the knee form give ``log_h_start``, ``knee`` and
        ``late_slope`` (scalars, or one per group) instead of ``log_h``.
    group_col, knots, ndt_values, n_quad, wall
        See fit_stopping_model.

    Returns
    -------
    float
    """
    x, lens, choice_pm, group_values, group_idx, post_mask = _prepare(data_table, group_col)
    G = len(group_values)
    p = {name: np.broadcast_to(np.asarray(params[name], float), (G,)) for name in GROUP_PARAMS}
    for name in POST_PARAMS:
        p[f"{name}_post"] = np.broadcast_to(np.asarray(params.get(f"{name}_post", params[name]), float), (G,))
    p["sensory_std"] = params["sensory_std"]
    p["log_h"] = np.atleast_2d(params.get("log_h", np.zeros(len(knots))))
    p["log_g"] = np.atleast_2d(params.get("log_g", np.zeros(len(knots))))
    if "knee" in params:
        for name in KNEE_PARAMS:
            p[name] = np.atleast_1d(np.asarray(params[name], float))
    lik = _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, p, knots, ndt_values,
                            np.asarray(params["ndt_probs"], float), n_quad=n_quad, wall=wall)
    return float(-np.sum(np.log(np.maximum(lik, _MIN_LIK))))


def fit_stopping_model(data_table, group_col="block_index", post_params=(), time_course="shared",
                       shared_params=SHARED_PARAMS, knots=KNOTS, ndt_values=NDT_VALUES, fixed=None,
                       smooth_penalty=2.0, anchor=ANCHOR, n_quad=24, wall=WALL, x0=None,
                       max_evals=200_000, guess_time_course="flat", time_course_form="knee",
                       time_course_col=None):
    """
    Maximum-likelihood fit of the stopping model to one subject's trials.

    Parameters
    ----------
    data_table : pd.DataFrame
        One subject's trials in get_data_table format: ``steps`` (on-screen
        positions, ``steps[0] = 0``), ``choice`` (0 = left, 1 = right), and
        optionally ``change_point`` (step index; 0 or NaN = none). Trial
        selection is the caller's job; rows with a missing choice raise.
    group_col : str or None
        Column whose values get separate per-group parameters.
    post_params : sequence of str
        Subset of POST_PARAMS with separate post-change-point values.
    time_course : {'flat', 'shared', 'per_group'}
        Bound time course across steps (see module docstring). Default
        'shared': one shape per subject (OL/MX model comparison: per-group
        shapes fit worse by AIC and are poorly recoverable at 33-150 trials
        per block).
    shared_params : sequence of str
        Subset of GROUP_PARAMS with one value shared by all groups. Default
        none: bound scale and CV, guess, lapse and anticipation rates are all
        per group (OL/MX: sharing the three rates is strongly rejected,
        dAIC +12,000 OL, +1,000 MX). Sensory noise and NDT are always shared.
    knots : sequence of int
        Steps at which log h is free (the first is fixed at 0).
    ndt_values : sequence of int
        NDT support; probabilities are fit and shared across groups.
    fixed : dict or None
        Parameters held fixed at natural-scale values, e.g.
        ``{'sensory_std': 0.0}`` (exact crossings) or ``{'guess_rate': 0.0}``.
    smooth_penalty : float
        Weight on squared adjacent differences of log h (0 = none). Default 2
        (prior SD 0.5 on each log change).
    anchor : int
        Knot at which h = 1 (bound_scale is the mean bound there).
    n_quad : int
        Quadrature nodes for the bound multiplier.
    wall : float
        Screen-edge position (see module docstring on wall-hit trials).
    x0 : array or None
        Starting point on the transformed scale; default is data-driven.
    max_evals : int
        Limit on objective evaluations (and iterations) for L-BFGS-B. With
        finite-difference gradients each iteration costs n_params + 1
        evaluations, so scipy's default (15,000) stops 40+-parameter fits
        after ~330 iterations, before convergence.
    guess_time_course : {'flat', 'shared', 'per_group'}
        Guess-rate time course: the guess rate at step j is
        ``expit(logit(guess_rate) + log_g(j))``, with ``log_g`` piecewise linear
        through ``knots``, 0 at ``anchor`` (so ``guess_rate`` is the rate at
        the anchor step), constant outside the knots (step 0 takes the first
        knot's value), and the same smoothing penalty as ``log h``. Default
        'flat' (constant guess rate).
    time_course_form : {'knee', 'knots'}
        Form of the bound time course (default 'knee', chosen by model
        comparison on OL/MX: dAIC -1,259 OL, -507 MX vs. knots at 1/6/16). 'knots': ``log h`` piecewise linear
        through ``knots``, 0 at ``anchor``. 'knee': linear from
        ``log_h_start`` at step 1 to 0 at a free knee step (``knee``, 1.5-15,
        continuous), then ``late_slope`` per step; ``bound_scale`` is then the
        bound at the knee. The penalty is ``smooth_penalty * (log_h_start**2 +
        (10 * late_slope)**2)`` (prior SD 0.5 on the early change and on the
        change over 10 late steps); the knee is unpenalized. Fix the late
        slope with ``fixed={'late_slope': 0.0}`` for a flat bound after the knee.
    time_course_col : str or None
        Column whose values get separate time-course shapes, independent of
        ``group_col`` (e.g. one shape per SNR while scale, CV and rates stay
        per block; a group may then mix shapes, as in mixed-SNR blocks).
        Overrides ``time_course`` ('flat' is not allowed). The output then
        has one row per (group, time-course value) present, with a
        ``time_course_group`` column; group parameters repeat across a
        group's rows, ``n_trials`` counts that row's trials. Such tables are
        for inspecting the fit (simulation and trial-level helpers reject them).

    Returns
    -------
    dict with keys
        ``params``      : pd.DataFrame, one row per group: natural-scale group
                          parameters, ``n_trials``, ``sensory_std``, ``ndt_p<v>``,
                          ``log_h_k<knot>`` (that group's bound time course;
                          ``log_h_start``, ``knee``, ``late_slope`` for the knee form)
                          and ``log_g_k<knot>`` (guess-rate time course)
        ``nll``         : float, negative log-likelihood (without the penalty)
        ``n_trials``    : int
        ``n_params``    : int, number of free parameters
        ``success``     : bool
        ``message``     : str
        ``theta``       : array, transformed-scale optimum
    """
    if data_table["choice"].isna().any():
        raise ValueError("fit_stopping_model: rows with missing choice; select trials first.")
    unknown = set(post_params) - set(POST_PARAMS)
    if unknown:
        raise ValueError(f"post_params must be a subset of {POST_PARAMS}; got {sorted(unknown)}.")
    if time_course not in TIME_COURSES or guess_time_course not in TIME_COURSES:
        raise ValueError(f"time_course and guess_time_course must be one of {TIME_COURSES}.")
    if time_course_form not in TIME_COURSE_FORMS:
        raise ValueError(f"time_course_form must be one of {TIME_COURSE_FORMS}.")

    x, lens, choice_pm, group_values, group_idx, post_mask = _prepare(data_table, group_col)
    G = len(group_values)
    if anchor not in knots:
        raise ValueError(f"anchor {anchor} must be one of the knots {tuple(knots)}.")
    tc_values, tc_idx = None, None
    if time_course_col is not None:
        if time_course == "flat":
            raise ValueError("time_course_col needs a bound time course (time_course != 'flat').")
        tc_values, tc_idx = np.unique(np.asarray(data_table[time_course_col]), return_inverse=True)
    lay = _Layout(G, post_params, len(ndt_values), time_course, len(knots), fixed, shared_params,
                  anchor_idx=list(knots).index(anchor), guess_time_course=guess_time_course,
                  time_course_form=time_course_form,
                  n_tc_groups=None if tc_values is None else len(tc_values))

    if x0 is None:
        k = np.clip(lens - 2, 0, x.shape[1] - 1)
        ax_k = np.abs(x[np.arange(len(k)), k])[k > 0]
        med = float(np.clip(np.nanmedian(ax_k) if ax_k.size else 0.1, 0.02, 1.0))
        step_sd = np.nanstd(np.diff(x, axis=1))
        start = {
            "bound_scale": np.full(G, np.log(med)), "bound_cv": np.full(G, np.log(0.4)),
            "guess_rate": np.full(G, scipy.special.logit(0.02)),
            "lapse_rate": np.full(G, scipy.special.logit(0.03)),
            "anticipation_rate": np.full(G, scipy.special.logit(max(np.mean(lens <= 2), 0.005))),
            "bound_scale_post": np.full(G, np.log(med)),
            "guess_rate_post": np.full(G, scipy.special.logit(0.02)),
            "sensory_std": np.array([np.log(max(0.3 * step_sd, 2e-3))]),
            "ndt_logits": np.zeros(len(ndt_values) - 1),
            "log_h": np.zeros(lay.n_shapes * lay.n_free_h),
            "log_g": np.zeros(lay.n_gshapes * lay.n_free_h),
            "log_h_start": np.zeros(lay.n_shapes), "knee": np.full(lay.n_shapes, 4.0),
            "late_slope": np.zeros(lay.n_shapes),
        }
        x0 = np.concatenate([start[name][:size] for name, size, _ in lay.spec])

    def objective(theta):
        p = lay.unpack(theta)
        lik = _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, p, knots, ndt_values,
                                p["ndt_probs"], n_quad=n_quad, wall=wall, shape_idx=tc_idx)
        nll = -np.sum(np.log(np.maximum(lik, _MIN_LIK)))
        if lay.knee:
            tc_pen = np.sum(p["log_h_start"] ** 2) + np.sum((10 * p["late_slope"]) ** 2)
        else:
            tc_pen = np.sum(np.diff(p["log_h"], axis=1) ** 2)
        penalty = tc_pen + np.sum(np.diff(p["log_g"], axis=1) ** 2)
        return nll + smooth_penalty * penalty, nll

    res = scipy.optimize.minimize(lambda t: objective(t)[0], x0, method="L-BFGS-B", bounds=lay.limits(),
                                  options={"maxfun": max_evals, "maxiter": max_evals})
    p = lay.unpack(res.x)

    cols = list(GROUP_PARAMS) + [f"{q}_post" for q in lay.post_params]
    table = pd.DataFrame({c: p[c] for c in cols})
    table.insert(0, "group", group_values)
    table["n_trials"] = np.bincount(group_idx, minlength=G)
    has_post = np.bincount(group_idx, weights=post_mask.any(axis=1), minlength=G) > 0
    for q in lay.post_params:
        table.loc[~has_post, f"{q}_post"] = np.nan
    table["sensory_std"] = p["sensory_std"]
    for v, pv in zip(ndt_values, p["ndt_probs"]):
        table[f"ndt_p{v}"] = pv
    lg = np.broadcast_to(p["log_g"], (G, len(knots)))
    if tc_values is not None:
        pass   # shapes are attached per (group, time-course value) row below
    elif lay.knee:
        for name in KNEE_PARAMS:
            table[name] = np.broadcast_to(p[name], (G,))
    else:
        lh = np.broadcast_to(p["log_h"], (G, len(knots)))
        for ki, kn in enumerate(knots):
            table[f"log_h_k{kn}"] = lh[:, ki]
    for ki, kn in enumerate(knots):
        table[f"log_g_k{kn}"] = lg[:, ki]
    if tc_values is not None:
        # One row per (group, time-course value) present, carrying that shape.
        pairs = pd.DataFrame({"g": group_idx, "s": tc_idx}).value_counts().sort_index()
        gi, si = (pairs.index.get_level_values(c).to_numpy() for c in ("g", "s"))
        table = table.iloc[gi].reset_index(drop=True)
        table.insert(1, "time_course_group", tc_values[si])
        table["n_trials"] = pairs.to_numpy()
        shape_cols = list(KNEE_PARAMS) if lay.knee else [f"log_h_k{kn}" for kn in knots]
        shapes = (np.stack([p[c] for c in KNEE_PARAMS], axis=1) if lay.knee
                  else np.broadcast_to(p["log_h"], (lay.n_shapes, len(knots))))
        table[shape_cols] = pd.DataFrame(shapes[si], columns=shape_cols)
    return {
        "params": table,
        "nll": float(objective(res.x)[1]),
        "n_trials": int(len(lens)),
        "n_params": int(len(res.x)),
        "success": bool(res.success),
        "message": str(res.message),
        "theta": res.x,
    }


def simulate_stopping_trials(num_trials, generative_mean, generative_std, bound_scale, bound_cv,
                             guess_rate=0.0, lapse_rate=0.0, anticipation_rate=0.0, sensory_std=0.0,
                             log_h=None, knots=KNOTS, ndt_values=NDT_VALUES, ndt_probs=(1.0, 0.0),
                             change_point=0, generative_mean_post=None, bound_scale_post=None,
                             guess_rate_post=None, max_steps=200, wall=WALL, rng=None, log_g=None,
                             knee_shape=None):
    """
    Simulate trials from the stopping model (the generative model fit by fit_stopping_model).

    Parameters
    ----------
    num_trials : int
    generative_mean, generative_std : float
        Step mean magnitude (sign drawn 50/50 per trial) and SD.
    bound_scale, bound_cv : float
        Mean bound at the anchor knot (position units) and the coefficient of
        variation of the per-trial bound multiplier.
    guess_rate, lapse_rate, anticipation_rate, sensory_std : float
        See module docstring.
    log_h : sequence or None
        log h at the knots (0 at the anchor knot); None = flat.
    knots : sequence of int
    ndt_values, ndt_probs : sequences
        NDT support and probabilities.
    change_point : int or (num_trials,) array
        Position index from which post values apply (0 = none). As in the task,
        the step that produces position ``change_point`` is the first drawn
        with ``generative_mean_post``.
    generative_mean_post, bound_scale_post, guess_rate_post : float or None
        Post-change-point values (None = same as pre).
    max_steps : int
        Walk length; trials with no commit by ``max_steps - max(ndt_values) - 1``
        commit there (``commit_type = 'cap'``).
    wall : float
        Displayed positions are clamped to +/-wall, as in the task.
    rng : np.random.Generator or None
    log_g : sequence or None
        Guess-rate time course at the knots (logit-scale shift, 0 at the
        anchor knot; see fit_stopping_model); None = constant.
    knee_shape : (log_h_start, knee, late_slope) or None
        Knee-form bound time course (see fit_stopping_model); overrides log_h.

    Returns
    -------
    pd.DataFrame with get_data_table-style columns ``steps``, ``RT``, ``choice``
    (0/1), ``correct``, ``change_point``, ``wall_hit``, plus ground truth:
    ``commit_step``, ``ndt``, ``commit_type`` ('anticipation', 'bound',
    'guess', 'cap'), ``bound_multiplier``, ``lapse``, and ``true_crossed``
    (the on-screen position, not only the perceived one, was at or beyond
    the trial's bound at the commit step, on the side the perceived position
    was on; False for anticipations).
    """
    if rng is None:
        rng = np.random.default_rng()
    n = int(num_trials)
    post = lambda v, d: d if v is None else v  # noqa: E731
    cp = np.broadcast_to(np.asarray(change_point, int), (n,))
    j = np.arange(max_steps + 1)[None, :]
    lpost = (cp[:, None] > 0) & (j >= cp[:, None])

    sgn = rng.choice([-1.0, 1.0], n)
    means = np.where(lpost[:, 1:], post(generative_mean_post, generative_mean), generative_mean) * sgn[:, None]
    walk = np.concatenate([np.zeros((n, 1)), np.cumsum(rng.normal(means, generative_std), axis=1)], axis=1)
    shown = np.clip(walk, -wall, wall)
    perceived = shown + (rng.normal(0, sensory_std, shown.shape) if sensory_std > 0 else 0.0)

    if knee_shape is not None:
        h = np.exp(_knee_log_h(*knee_shape, np.arange(max_steps + 1)))
    else:
        lh = np.zeros(len(knots)) if log_h is None else np.asarray(log_h, float)
        h = np.exp(np.interp(np.arange(max_steps + 1), knots, lh))[None, :]
    theta = np.where(lpost, post(bound_scale_post, bound_scale), bound_scale) * h
    mult = _gamma_ppf(rng.random(n), bound_cv)
    hit_bound = np.abs(perceived) >= theta * mult[:, None]
    gr = np.where(lpost, post(guess_rate_post, guess_rate), guess_rate)
    if log_g is not None:
        gr = _shift_logit(gr, np.interp(np.arange(max_steps + 1), knots, np.asarray(log_g, float))[None, :])
    hit_guess = rng.random((n, max_steps + 1)) < gr
    hit_bound[:, 0] = False   # no evidence at the start frame; guesses there are allowed

    last = max_steps - max(ndt_values) - 1
    big = max_steps + 10
    kb = np.where(hit_bound.any(1), hit_bound.argmax(1), big)
    kg = np.where(hit_guess.any(1), hit_guess.argmax(1), big)
    k = np.minimum(kb, kg)
    ctype = np.where(kb <= kg, "bound", "guess").astype(object)
    ctype[k > last] = "cap"
    k = np.minimum(k, last)

    ndt = rng.choice(np.asarray(ndt_values), n, p=np.asarray(ndt_probs) / np.sum(ndt_probs))
    rows = np.arange(n)
    side = np.sign(perceived[rows, k])
    lapse = rng.random(n) < lapse_rate
    rand_side = rng.choice([-1.0, 1.0], n)
    choice = np.where(lapse | (side == 0), rand_side, side)
    rt = k + ndt + 1

    lant = rng.random(n) < anticipation_rate
    rt[lant] = 1                                 # key pressed during the first frame
    choice[lant] = rand_side[lant]
    k[lant] = 0
    ctype[lant] = "anticipation"

    # Whether the on-screen position itself had reached the bound at the commit step, on the side the
    # perceived position crossed (a bound commit without it was triggered by sensory noise, including
    # noise that put the perceived position across the bound on the other side).
    theta_k = np.broadcast_to(theta, (n, max_steps + 1))[rows, k] * mult
    true_crossed = (shown[rows, k] * side >= theta_k) & (k > 0) & ~lant
    steps = [shown[tt, : rt[tt]] for tt in range(n)]
    return pd.DataFrame({
        "steps": steps,
        "RT": rt,
        "choice": (choice > 0).astype(float),
        "correct": (choice == sgn).astype(float),
        "change_point": cp.astype(float),
        "wall_hit": [bool(np.any(np.abs(s) >= wall - 1e-9)) for s in steps],
        "commit_step": k,
        "ndt": ndt,
        "commit_type": ctype,
        "bound_multiplier": mult,
        "lapse": lapse & ~lant,
        "true_crossed": true_crossed,
    })


def _params_from_fits(fit_rows, knots=KNOTS):
    """Natural-scale parameter dict (stopping_model_nll format) from one subject's fit rows, sorted by group."""
    if "time_course_group" in fit_rows:
        raise ValueError("Fits with time_course_col (one row per group x time-course value) are not supported here.")
    f = fit_rows.sort_values("group")
    params = {name: f[name].to_numpy(float) for name in GROUP_PARAMS}
    for name in POST_PARAMS:
        if f"{name}_post" in f:
            params[f"{name}_post"] = np.where(np.isfinite(f[f"{name}_post"]), f[f"{name}_post"], f[name])
    params["sensory_std"] = float(f["sensory_std"].iloc[0])
    ndt_cols = sorted((c for c in f.columns if c.startswith("ndt_p")), key=lambda c: int(c[5:]))
    params["ndt_probs"] = f[ndt_cols].iloc[0].to_numpy(float)
    if "knee" in f and np.isfinite(f["knee"]).all():
        for name in KNEE_PARAMS:
            params[name] = f[name].to_numpy(float)
    else:
        params["log_h"] = np.stack([f.get(f"log_h_k{k}", pd.Series(0.0, index=f.index)).to_numpy(float)
                                    for k in knots], axis=1)
    if f"log_g_k{knots[0]}" in f and np.isfinite(f[f"log_g_k{knots[0]}"]).all():
        params["log_g"] = np.stack([f[f"log_g_k{k}"].to_numpy(float) for k in knots], axis=1)
    return params


def get_commit_type_probabilities(data_table, fits, group_col="condition", knots=KNOTS, ndt_values=NDT_VALUES,
                                  n_quad=24, wall=WALL):
    """
    Posterior probability that each trial's commit was a guess, under the fitted model.

    For each trial, the likelihood of its (RT, choice) splits into a part from
    bound crossings and a part from guesses (including start-frame guesses
    and anticipations), averaged over NDT; ``p_guess`` is the guess part's
    share. Wall-censored trials (answered later than any NDT allows after the
    pigeon reached the wall) have no defined commit type and get NaN.

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials (``subject_index``, ``group_col``, ``steps``, ``choice``,
        optional ``change_point``). Trials need not be the ones fit.
    fits : pd.DataFrame
        Output of fit_stopping_models with the same grouping.
    group_col, knots, ndt_values, n_quad, wall
        As in fit_stopping_model.

    Returns
    -------
    pd.Series ``p_guess`` (index of data_table); NaN for wall-censored trials
    and subjects or groups without a fit.
    """
    out = pd.Series(np.nan, index=data_table.index, name="p_guess")
    for d, args, kwargs in _subject_likelihood_inputs(data_table, fits, group_col, knots):
        lik, lik_guess, lik_wall = _trial_likelihood(*args, **kwargs, ndt_values=ndt_values, n_quad=n_quad,
                                                     wall=wall, return_parts=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            pg = np.where(lik_wall > 0, np.nan, lik_guess / lik)
        out.loc[d.index] = pg
    return out


def _subject_likelihood_inputs(data_table, fits, group_col, knots):
    """Per subject with fits: (trials, positional args, keyword args) for _trial_likelihood."""
    for subject, d in data_table.groupby("subject_index"):
        f = fits[(fits["subject_index"] == subject) & fits["bound_scale"].notna()]
        d = d[d[group_col].isin(f["group"])]
        if d.empty:
            continue
        f = f[f["group"].isin(d[group_col])]
        p = _params_from_fits(f, knots)
        x, lens, choice_pm, group_values, group_idx, post_mask = _prepare(d, group_col)
        G = len(group_values)
        q = {name: np.broadcast_to(np.asarray(p[name], float), (G,)) for name in GROUP_PARAMS}
        for name in POST_PARAMS:
            q[f"{name}_post"] = np.broadcast_to(np.asarray(p.get(f"{name}_post", p[name]), float), (G,))
        q["sensory_std"] = p["sensory_std"]
        q["log_h"] = np.atleast_2d(p.get("log_h", np.zeros(len(knots))))
        q["log_g"] = np.atleast_2d(p.get("log_g", np.zeros(len(knots))))
        if "knee" in p:
            for name in KNEE_PARAMS:
                q[name] = p[name]
        yield d, (x, lens, choice_pm, group_idx, post_mask, q, knots), {"ndt_probs": p["ndt_probs"]}


def get_choice_probabilities(data_table, fits, group_col="condition", knots=KNOTS, ndt_values=NDT_VALUES,
                             n_quad=24, wall=WALL):
    """
    Model probability of a rightward choice on each trial, given its trajectory and RT.

    P(right | steps, RT) = L(RT, right) / (L(RT, right) + L(RT, left)) under the
    subject's fitted parameters: the model's prediction of the choice once the
    trial's positions up to the key press and its timing are known (it uses the
    positions only up to the press, so it does not peek at anything the
    subject could not have seen).

    Parameters
    ----------
    data_table : pd.DataFrame
        Trials (``subject_index``, ``group_col``, ``steps``, ``choice``,
        optional ``change_point``).
    fits : pd.DataFrame
        Output of fit_stopping_models with the same grouping.
    group_col, knots, ndt_values, n_quad, wall
        As in fit_stopping_model.

    Returns
    -------
    pd.Series ``p_right`` (index of data_table); NaN for subjects or groups
    without a fit.
    """
    out = pd.Series(np.nan, index=data_table.index, name="p_right")
    for d, (x, lens, _, group_idx, post_mask, q, knots_), kwargs in _subject_likelihood_inputs(
            data_table, fits, group_col, knots):
        common = dict(ndt_values=ndt_values, n_quad=n_quad, wall=wall, **kwargs)
        ones = np.ones(len(lens))
        lik_r = _trial_likelihood(x, lens, ones, group_idx, post_mask, q, knots_, **common)
        lik_l = _trial_likelihood(x, lens, -ones, group_idx, post_mask, q, knots_, **common)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.loc[d.index] = lik_r / (lik_r + lik_l)
    return out


def _fit_one_subject(args):
    """Worker for fit_stopping_models (module level so it can run in a process pool)."""
    subject, table, kwargs = args
    try:
        fit = fit_stopping_model(table, **kwargs)
    except Exception as err:  # report per-subject failures instead of losing the whole run
        return subject, None, repr(err)
    return subject, fit, None


def fit_stopping_models(data_table, max_workers=None, **kwargs):
    """
    Fit the stopping model separately to every subject in a data table.

    Parameters
    ----------
    data_table : pd.DataFrame
        Selected trials (``subject_index``, ``steps``, ``choice``, optional
        ``change_point``, and the grouping column).
    max_workers : int or None
        Processes for the per-subject fits (None = all cores; 1 = no pool).
    **kwargs
        Passed to fit_stopping_model (group_col, post_params, time_course,
        shared_params, knots, anchor, ndt_values, fixed, smooth_penalty, n_quad, wall).

    Returns
    -------
    pd.DataFrame, one row per (subject, group): ``subject_index`` plus
    fit_stopping_model's ``params`` columns, and per-subject ``nll``,
    ``n_params``, ``success``, ``error`` (message if the fit raised; such
    subjects have NaN parameters and are never dropped).
    """
    jobs = [(s, g, kwargs) for s, g in data_table.groupby("subject_index")]
    if max_workers == 1:
        results = [_fit_one_subject(job) for job in jobs]
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_fit_one_subject, jobs))

    rows = []
    for subject, fit, err in results:
        if fit is None:
            rows.append(pd.DataFrame({"subject_index": [subject], "success": [False], "error": [err]}))
            continue
        t = fit["params"].copy()
        t.insert(0, "subject_index", subject)
        t["nll"], t["n_params"], t["success"], t["message"], t["error"] = (
            fit["nll"], fit["n_params"], fit["success"], fit["message"], None)
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


def simulate_stopping_data_table(data_table, fits, group_col="block_index", post_generative_mean=None,
                                 knots=KNOTS, ndt_values=NDT_VALUES, num_reps=1, max_steps=200,
                                 wall=WALL, rng=None):
    """
    Simulate each subject's trials from their fitted stopping-model parameters.

    Every real trial is replaced by ``num_reps`` simulated trials with the
    same subject, group, generative step mean and SD (``|snr| * step_std``,
    ``step_std``) and change point, so trial counts and SNR mix match the data.

    Parameters
    ----------
    data_table : pd.DataFrame
        The trials the fits were made on (``subject_index``, ``group_col``,
        ``snr``, ``step_std``, ``block_index``, optional ``change_point``).
    fits : pd.DataFrame
        Output of fit_stopping_models.
    group_col : str
        Column the fits were grouped by.
    post_generative_mean : dict or None
        {block_index: post-change step mean magnitude} for change-point
        blocks; required if any trial has a change point.
    knots, ndt_values : sequences
        Must match the fits.
    num_reps : int
    max_steps, wall : see simulate_stopping_trials.
    rng : np.random.Generator or None

    Returns
    -------
    pd.DataFrame from simulate_stopping_trials plus ``subject_index``,
    ``group_col``, ``block_index``, ``snr`` (abs), ``rep``.
    """
    if "time_course_group" in fits:
        raise ValueError("Fits with time_course_col (one row per group x time-course value) are not supported here.")
    if rng is None:
        rng = np.random.default_rng()
    d = data_table.copy()
    d["_mean"] = (d["snr"].abs() * d["step_std"]).round(6)
    d["_cp"] = d["change_point"].fillna(0).astype(int) if "change_point" in d else 0
    fits = fits.set_index(["subject_index", "group"])
    out = []
    for (subject, group, block, mean, std), cell in d.groupby(
            ["subject_index", group_col, "block_index", "_mean", "step_std"]):
        f = fits.loc[(subject, group)]
        if not np.isfinite(f["bound_scale"]):
            continue
        cps = np.tile(cell["_cp"].to_numpy(), num_reps)
        post = {}
        if np.any(cps > 0):
            post = {"generative_mean_post": post_generative_mean[block]}
            for name in POST_PARAMS:
                if f"{name}_post" in f and np.isfinite(f[f"{name}_post"]):
                    post[f"{name}_post"] = f[f"{name}_post"]
        sim = simulate_stopping_trials(
            len(cps), mean, std, f["bound_scale"], f["bound_cv"], f["guess_rate"], f["lapse_rate"],
            f["anticipation_rate"], f["sensory_std"],
            log_h=[f.get(f"log_h_k{kn}", 0.0) for kn in knots], knots=knots, ndt_values=ndt_values,
            knee_shape=(tuple(f[c] for c in KNEE_PARAMS) if np.isfinite(f.get("knee", np.nan)) else None),
            # Fits made without a guess time course have no (or NaN) log_g columns: constant guessing.
            log_g=([f[f"log_g_k{kn}"] for kn in knots]
                   if np.isfinite(f.get(f"log_g_k{knots[0]}", np.nan)) else None),
            ndt_probs=[f[f"ndt_p{v}"] for v in ndt_values], change_point=cps,
            max_steps=max_steps, wall=wall, rng=rng, **post)
        sim.insert(0, "subject_index", subject)
        sim[group_col], sim["block_index"], sim["snr"] = group, block, mean / std
        sim["rep"] = np.repeat(np.arange(num_reps), len(cell))
        out.append(sim)
    return pd.concat(out, ignore_index=True)


def infer_bounds_like_data(sim_table, max_ndt=5, peak_step_bound=True):
    """
    Run the real-data bound inference on simulated trials.

    Calls ``get_bounds`` once per subject, with the same arguments
    ``get_data_table`` uses for OL/MX/MXSC (NDT estimated by congruence,
    per-block/SNR RT cutoffs), so simulated trials get ``bound``, ``DT``,
    ``rt_below_cutoff`` and ``abs_bound`` exactly as real ones do. No bias
    correction (apply ``apply_bias_corrections`` afterwards if needed).

    Parameters
    ----------
    sim_table : pd.DataFrame
        Output of simulate_stopping_data_table (``subject_index``, ``steps``,
        ``choice``, ``snr``, ``block_index``; ``rep`` if present is treated as a
        separate subject-session).
    max_ndt, peak_step_bound
        Passed to get_bounds (get_data_table's defaults).

    Returns
    -------
    Copy of sim_table with ``bound``, ``abs_bound``, ``DT``, ``rt_cutoff`` and
    ``rt_below_cutoff`` added.
    """
    out = sim_table.copy()
    keys = ["subject_index", "rep"] if "rep" in out else ["subject_index"]
    for col in ("bound", "DT", "rt_cutoff"):
        out[col] = np.nan
    for _, g in out.groupby(keys):
        bounds, dts, rts, _, cutoffs = get_bounds(
            list(g["steps"]), g["choice"].to_numpy(float), snr=np.abs(g["snr"].to_numpy(float)),
            block_ids=g["block_index"].to_numpy(float), ndt=None, max_ndt=max_ndt,
            peak_step_bound=peak_step_bound)
        out.loc[g.index, "bound"] = bounds
        out.loc[g.index, "DT"] = dts
        out.loc[g.index, "rt_cutoff"] = cutoffs
    out["abs_bound"] = out["bound"].abs()
    out["rt_below_cutoff"] = out["RT"] < out["rt_cutoff"]
    return out


def get_stopping_model_trials(task_type, blocks, min_trial_number=10, tau_exclusion=True, verbose=True):
    """
    Trials for stopping-model fits, following the paper's trial conventions.

    Loads the raw block numbering (``combine_snr=False``; OL and MX each have
    six blocks run in order 1-6), keeps ``trial_number >= min_trial_number`` and
    trials with a recorded choice (trials without one ran out of the block's
    step budget), and, if ``tau_exclusion``, drops each subject's adaptation
    transient: trials with ``trial_number < ceil(tau)`` in blocks where the
    subject has a good adaptation fit (``get_adaptation_tau_fits`` on the
    standard bias-corrected table, as in Figure04_RRvsBound and
    Figure03S04/S06). No DT cutoff, no wall-hit exclusion, and positions are
    raw (no bias correction) for the model itself.

    Parameters
    ----------
    task_type : str
        'OL', 'MX' or 'MXSC'.
    blocks : sequence of int
        Raw block_index values to keep, in presentation order.
    min_trial_number : int
    tau_exclusion : bool
        Apply the adaptation-transient exclusion.
    verbose : bool
        Print the number of trials excluded by each criterion.

    Returns
    -------
    pd.DataFrame (get_data_table columns plus ``condition`` = 'B<block>' and
    ``task``).
    """
    from .adaptation import get_adaptation_tau_fits, get_tau_exclusion_mask

    blocks = list(blocks)
    d = get_data_table(task_type=task_type, combine_snr=False, correct_bias=None)
    d = d[d["block_index"].isin(blocks)]
    l_early = d["trial_number"] < min_trial_number
    l_nochoice = d["choice"].isna()
    l_tau = pd.Series(False, index=d.index)
    if tau_exclusion:
        dc = get_data_table(task_type=task_type, combine_snr=False)
        good_tau = get_adaptation_tau_fits(dc[dc["block_index"].isin(blocks)], blocks=blocks,
                                           max_trial=40)["good_tau"]
        l_tau = ~get_tau_exclusion_mask(d, good_tau)
        if verbose:
            print(f"{task_type}: subjects with a good adaptation tau fit, by block: "
                  f"{good_tau.notna().sum().to_dict()}")
    if verbose:
        print(f"{task_type}: {len(d):,} trials in blocks {blocks}; excluded {l_early.sum():,} with "
              f"trial_number < {min_trial_number}, {(l_tau & ~l_early).sum():,} more in the adaptation "
              f"transient, {(l_nochoice & ~l_early & ~l_tau).sum():,} more with no choice; "
              f"{d['subject_index'].nunique()} subjects")
    d = d[~l_early & ~l_tau & ~l_nochoice].copy()
    d["condition"] = [f"B{b:.0f}" for b in d["block_index"]]
    d["task"] = task_type
    return d


def get_bound_residuals(data_table, fits, group_col="condition", num_reps=20, max_dt=10, min_sim_trials=20,
                        knots=KNOTS, ndt_values=NDT_VALUES, rng=None):
    """
    Trial-by-trial deviation of the measured bound from the model's expected measured bound.

    Each subject x group is simulated ``num_reps`` times over its trials from
    its fitted (steady-state) parameters, and the simulated trials are run
    through the real-data bound inference (``infer_bounds_like_data``: same
    ``get_bounds`` call, congruence-based NDT and DT). The expected measured
    |bound| (and log |bound|) at each DT is the mean over simulated trials
    that pass the standard filter without a trial-number floor
    (``get_good_trial_array(min_trial_number=None)``: DT >= 2, no wall hit,
    RT cutoff) and have a nonzero bound. Overshoot, the DT assignment and the
    bound's within-trial time course are thus in the expectation, so the
    residual isolates deviations from the subject's steady state (e.g.
    adaptation at the start of a block).

    Parameters
    ----------
    data_table : pd.DataFrame
        Real trials with raw (not bias-corrected) ``bound`` and get_bounds'
        ``DT`` (``get_data_table(..., correct_bias=None)``), plus
        ``group_col``, ``snr``, ``step_std``, ``block_index``.
    fits : pd.DataFrame
        Output of fit_stopping_models with the same grouping.
    group_col : str
    num_reps : int
        Simulated repetitions of each real trial.
    max_dt : int
        DT values >= max_dt are pooled.
    min_sim_trials : int
        Expected values from fewer simulated trials are NaN (and so are those
        trials' residuals).
    knots, ndt_values : sequences
        Must match the fits.
    rng : np.random.Generator or None

    Returns
    -------
    pd.DataFrame (index of data_table) with ``expected_abs_bound``,
    ``expected_log_abs_bound``, ``bound_residual`` (|bound| - expected) and
    ``log_bound_residual`` (log |bound| - expected log |bound|). NaN where the
    trial's bound is missing or zero, or the expectation is undetermined.
    """
    if rng is None:
        rng = np.random.default_rng()
    have_fit = data_table.set_index(["subject_index", group_col]).index.isin(
        fits.loc[fits["bound_scale"].notna()].set_index(["subject_index", "group"]).index)
    d = data_table[have_fit & data_table["choice"].notna()]
    sim = simulate_stopping_data_table(d, fits, group_col=group_col, knots=knots, ndt_values=ndt_values,
                                       num_reps=num_reps, rng=rng)
    sim = infer_bounds_like_data(sim)
    ls = (get_good_trial_array(sim, min_trial_number=None) & np.isfinite(sim["bound"]) & (sim["bound"] != 0))
    sim = sim[ls].assign(dt_bin=lambda t: t["DT"].clip(upper=max_dt), log_abs=lambda t: np.log(t["bound"].abs()))
    g = sim.groupby(["subject_index", group_col, "dt_bin"])
    expect = pd.DataFrame({"expected_abs_bound": g["abs_bound"].mean(),
                           "expected_log_abs_bound": g["log_abs"].mean(), "n_sim": g.size()})
    expect.loc[expect["n_sim"] < min_sim_trials, ["expected_abs_bound", "expected_log_abs_bound"]] = np.nan

    key = pd.MultiIndex.from_arrays([data_table["subject_index"], data_table[group_col],
                                     data_table["DT"].clip(upper=max_dt)])
    e = expect.reindex(key)
    out = pd.DataFrame({"expected_abs_bound": e["expected_abs_bound"].to_numpy(),
                        "expected_log_abs_bound": e["expected_log_abs_bound"].to_numpy()}, index=data_table.index)
    ab = data_table["bound"].abs().where(data_table["bound"] != 0)
    out["bound_residual"] = ab - out["expected_abs_bound"]
    with np.errstate(divide="ignore"):
        out["log_bound_residual"] = np.log(ab) - out["expected_log_abs_bound"]
    return out
