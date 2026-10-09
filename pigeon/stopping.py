"""
Trial-level stopping model: variable bound, guesses, anticipations, and choice lapses.

Fits *when* a subject commits and *which* side they choose from the pigeon's
full on-screen path on every trial, instead of inferring one bound per trial
and filtering out the trials that don't fit (DT cutoffs). Used by
notebooks/Test_stoppingModel.ipynb.

Generative model (per trial)
----------------------------
Positions ``x_0 = 0, x_1, x_2, ...`` are the pigeon's on-screen positions (the
``steps`` column of ``get_data_table``; clamped at +/-WALL by the task).

1. **Anticipation.** With probability ``anticipation_rate`` the subject commits
   before any step is shown (commit step k <= 0). The choice is random, and
   the response comes uniformly within the first NDT + 1 frames.
2. **Variable bound.** Otherwise each trial draws a bound percentile
   ``u ~ U(0, 1)``; the bound at step j is ``F_j^{-1}(u)``, where ``F_j`` is the
   CDF of a gamma distribution with mean ``bound_mean`` and SD ``bound_std``
   (the ``_post`` values for steps j >= change_point on change-point trials).
   The bound commits at the first j >= 1 with ``F_j(|x_j|) >= u``. Keeping the
   percentile fixed means a trial's bound stays relatively high or low across
   the change point.
3. **Guess.** Independently, at every step j >= 1 the subject commits with
   probability ``guess_rate`` regardless of the evidence.
4. **Choice.** The side the pigeon is on at the commit step, except that with
   probability ``lapse_rate`` the choice is random (random also at x = 0).
5. **NDT.** The response comes NDT + 1 frames after the commit step,
   ``RT = k + NDT + 1`` (the ``DT = RT - NDT - 1`` convention of ``get_bounds``),
   with NDT drawn from ``ndt_probs`` over ``ndt_values``.

Likelihood
----------
With ``A_k = max_{1<=j<=k} F_j(|x_j|)`` (``A_0 = 0``) and
``G_k = prod_{j=1..k} (1 - guess_rate_j)``, the probability of no commit
through step k is ``S_k = (1 - anticipation_rate) * G_k * (1 - A_k)``, so
P(commit at k) = ``S_{k-1} - S_k`` for k >= 1. A bound can only fire when the
pigeon reaches a new maximum distance from center; a guess can fire anywhere.
That difference is what separates guesses from low bounds. Each trial's
likelihood averages over NDT.

**Wall-hit trials.** Once the pigeon reaches the wall (first step w with
|x_w| >= WALL) it stays at the edge until the key press, so a long RT after
that carries no information about stopping. A wall trial whose response came
later than any NDT allows (RT > w + max(ndt_values) + 1) contributes
``S_{w-1}`` (no commit before the wall) times the choice probability at the
wall, instead of a point probability. Wall trials answered within that window
use the ordinary likelihood. (Censoring only per NDT value instead lets the
censored mass compete with point probabilities and biases NDT and the bound
upward; see tests/test_stopping.py.)

Fitting
-------
``fit_stopping_model`` maximizes the likelihood over all trials of one
subject with ``scipy.optimize.minimize`` (L-BFGS-B), on transformed scales
(log bound_mean/std, logit rates, softmax NDT). Bound, guess, lapse and
anticipation parameters are per group (e.g. per block); NDT probabilities are
shared across groups. ``post_params`` adds separate post-change-point values.

Units: ``bound_mean`` and ``bound_std`` are in position units (the same units as
the ``bound`` column), on *raw* positions -- no bias correction, because the
likelihood accounts for overshoot directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.optimize
import scipy.special
import scipy.stats

from .data import WALL

NDT_VALUES = (1, 2, 3)
GROUP_PARAMS = ("bound_mean", "bound_std", "guess_rate", "lapse_rate", "anticipation_rate")
POST_PARAMS = ("bound_mean", "bound_std", "guess_rate")

# Transformed-parameter limits for the optimizer: bounds 0.002-2 (position
# units), rates 1e-6 to ~0.9998 (logit +/-8.5 with a small margin).
_LOG_POS_LIMITS = (np.log(0.002), np.log(2.0))
_LOGIT_LIMITS = (-14.0, 8.5)
_NDT_LOGIT_LIMITS = (-10.0, 10.0)
_MIN_LIK = 1e-300


def _gamma_cdf(x, mean, std):
    """Gamma CDF parameterized by mean and SD (elementwise, broadcastable)."""
    shape = (mean / std) ** 2
    scale = std ** 2 / mean
    return scipy.stats.gamma.cdf(x, a=shape, scale=scale)


def _gamma_ppf(q, mean, std):
    """Gamma quantile function parameterized by mean and SD."""
    shape = (mean / std) ** 2
    scale = std ** 2 / mean
    return scipy.stats.gamma.ppf(q, a=shape, scale=scale)


def _pad_steps(steps_list):
    """Stack variable-length position sequences into an (n, max_len) NaN-padded array."""
    lens = np.array([np.sum(np.isfinite(np.asarray(s, float))) for s in steps_list])
    x = np.full((len(steps_list), int(lens.max())), np.nan)
    for tt, s in enumerate(steps_list):
        s = np.asarray(s, float)
        s = s[np.isfinite(s)]
        x[tt, : len(s)] = s
    return x, lens


def _per_step(param_pre, param_post, group_idx, post_mask):
    """(n, L) matrix of a parameter: post value where post_mask, else pre value."""
    pre = np.asarray(param_pre)[group_idx][:, None]
    post = np.asarray(param_post)[group_idx][:, None]
    return np.where(post_mask, post, pre)


def _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, params, ndt_values, ndt_probs,
                      wall=WALL):
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
    params : dict
        Per-group arrays for GROUP_PARAMS, and ``<name>_post`` for POST_PARAMS
        (equal to the pre values when not split).
    ndt_values, ndt_probs : sequences
        NDT support and probabilities.

    Returns
    -------
    (n,) array of likelihoods.
    """
    n, L = x.shape
    ax = np.abs(np.nan_to_num(x, nan=0.0))

    bm = _per_step(params["bound_mean"], params["bound_mean_post"], group_idx, post_mask)
    bs = _per_step(params["bound_std"], params["bound_std_post"], group_idx, post_mask)
    gr = _per_step(params["guess_rate"], params["guess_rate_post"], group_idx, post_mask)
    lapse = np.asarray(params["lapse_rate"])[group_idx]
    antic = np.asarray(params["anticipation_rate"])[group_idx]

    # A_k: running max of F_j(|x_j|) over j >= 1 (A_0 = 0 since x_0 = 0).
    f = _gamma_cdf(ax, bm, bs)
    f[:, 0] = 0.0
    a_run = np.maximum.accumulate(f, axis=1)
    # G_k: probability of no guess through step k (G_0 = 1).
    g_surv = np.cumprod(np.where(np.arange(L) == 0, 1.0, 1.0 - gr), axis=1)
    surv = (1.0 - antic)[:, None] * g_surv * (1.0 - a_run)  # S_k, k = 0..L-1

    # Choice probability if the commit is at step k.
    sgn = np.sign(np.nan_to_num(x, nan=0.0))
    p_choice = np.where(
        sgn == 0, 0.5,
        np.where(sgn == choice_pm[:, None], 1.0 - lapse[:, None] / 2, lapse[:, None] / 2),
    )

    # First step at the wall (L if never).
    at_wall = ax >= wall - 1e-9
    wall_step = np.where(at_wall.any(axis=1), at_wall.argmax(axis=1), L)

    rows = np.arange(n)
    # Wall trials whose response came too late for any NDT after the wall: the
    # commit was at or after the wall step, timing unknown (censored).
    lw = lens > wall_step + max(ndt_values) + 1
    w = wall_step[lw]
    lik = np.zeros(n)
    lik[lw] = surv[rows[lw], w - 1] * p_choice[rows[lw], w]

    for ndt, p_ndt in zip(ndt_values, ndt_probs):
        k = lens - ndt - 1
        term = np.zeros(n)

        lant = ~lw & (k <= 0)
        term[lant] = antic[lant] / (ndt + 1) * 0.5

        lk = ~lw & ~lant
        kk = k[lk]
        term[lk] = (surv[rows[lk], kk - 1] - surv[rows[lk], kk]) * p_choice[rows[lk], kk]

        lik += p_ndt * np.maximum(term, 0.0)
    return lik


def _unpack(theta, n_groups, post_params, n_ndt):
    """Map the unconstrained parameter vector to natural-scale parameter arrays."""
    i = 0

    def take(m):
        nonlocal i
        out = theta[i:i + m]
        i += m
        return out

    p = {
        "bound_mean": np.exp(take(n_groups)),
        "bound_std": np.exp(take(n_groups)),
        "guess_rate": scipy.special.expit(take(n_groups)),
        "lapse_rate": scipy.special.expit(take(n_groups)),
        "anticipation_rate": scipy.special.expit(take(n_groups)),
    }
    for name in POST_PARAMS:
        if name in post_params:
            raw = take(n_groups)
            p[f"{name}_post"] = scipy.special.expit(raw) if name == "guess_rate" else np.exp(raw)
        else:
            p[f"{name}_post"] = p[name]
    ndt_logits = np.r_[0.0, take(n_ndt - 1)]
    ndt_probs = np.exp(ndt_logits - scipy.special.logsumexp(ndt_logits))
    return p, ndt_probs


def _prepare(data_table, group_col):
    """Arrays the likelihood needs, from a get_data_table-style DataFrame."""
    x, lens = _pad_steps(list(data_table["steps"]))
    choice_pm = data_table["choice"].to_numpy(float) * 2 - 1
    groups = np.asarray(data_table[group_col]) if group_col is not None else np.zeros(len(data_table))
    group_values, group_idx = np.unique(groups, return_inverse=True)
    cp = (data_table["change_point"].fillna(0).to_numpy(float)
          if "change_point" in data_table else np.zeros(len(data_table)))
    steps_idx = np.arange(x.shape[1])[None, :]
    post_mask = (cp[:, None] > 0) & (steps_idx >= cp[:, None])
    return x, lens, choice_pm, group_values, group_idx, post_mask


def stopping_model_nll(data_table, params, ndt_probs, group_col="block_index",
                       ndt_values=NDT_VALUES, wall=WALL):
    """
    Negative log-likelihood of a data table under given stopping-model parameters.

    Parameters
    ----------
    data_table : pd.DataFrame
        get_data_table-style rows (``steps``, ``choice``, optionally
        ``change_point`` and ``group_col``).
    params : dict
        Natural-scale parameters: GROUP_PARAMS and ``<name>_post`` for
        POST_PARAMS, each a scalar or one value per group (sorted group order).
    ndt_probs : sequence of float
        P(NDT = v) for v in ``ndt_values``.
    group_col : str or None
        Column that indexes the per-group parameters.
    ndt_values : sequence of int
        NDT support.
    wall : float
        Screen-edge position.

    Returns
    -------
    float
    """
    x, lens, choice_pm, group_values, group_idx, post_mask = _prepare(data_table, group_col)
    n_groups = len(group_values)
    full = {}
    for name in GROUP_PARAMS:
        full[name] = np.broadcast_to(np.asarray(params[name], float), (n_groups,))
    for name in POST_PARAMS:
        full[f"{name}_post"] = np.broadcast_to(
            np.asarray(params.get(f"{name}_post", params[name]), float), (n_groups,))
    lik = _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, full,
                            ndt_values, np.asarray(ndt_probs, float), wall=wall)
    return float(-np.sum(np.log(np.maximum(lik, _MIN_LIK))))


def fit_stopping_model(data_table, group_col="block_index", post_params=(),
                       ndt_values=NDT_VALUES, wall=WALL, x0=None):
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
        Column whose values get separate bound/guess/lapse/anticipation
        parameters (e.g. ``"block_index"``). None fits one set.
    post_params : sequence of str
        Subset of POST_PARAMS that get separate post-change-point values.
    ndt_values : sequence of int
        NDT support; probabilities are fit and shared across groups.
    wall : float
        Screen-edge position (see module docstring on wall-hit trials).
    x0 : array or None
        Starting point on the transformed scale; default is a data-driven guess.

    Returns
    -------
    dict with keys
        ``params``     : pd.DataFrame, one row per group, natural-scale parameters
        ``ndt_probs``  : dict {ndt: probability}
        ``nll``        : float, minimized negative log-likelihood
        ``n_trials``   : int
        ``n_params``   : int
        ``success``    : bool, optimizer convergence flag
        ``message``    : str, optimizer message
        ``theta``      : array, transformed-scale optimum
    """
    if data_table["choice"].isna().any():
        raise ValueError("fit_stopping_model: rows with missing choice; select trials first.")
    unknown = set(post_params) - set(POST_PARAMS)
    if unknown:
        raise ValueError(f"post_params must be a subset of {POST_PARAMS}; got {sorted(unknown)}.")

    x, lens, choice_pm, group_values, group_idx, post_mask = _prepare(data_table, group_col)
    n_groups, n_ndt = len(group_values), len(ndt_values)
    post_params = tuple(p for p in POST_PARAMS if p in post_params)

    if x0 is None:
        # Start the bound at the median |position| at the DT-convention commit step (NDT = 1).
        k = np.clip(lens - 2, 0, x.shape[1] - 1)
        med = np.nanmedian(np.abs(x[np.arange(len(k)), k])[k > 0]) if np.any(k > 0) else 0.1
        med = float(np.clip(med, 0.02, 1.0))
        blocks = [np.full(n_groups, np.log(med)), np.full(n_groups, np.log(med / 2)),
                  np.full(n_groups, scipy.special.logit(0.02)),
                  np.full(n_groups, scipy.special.logit(0.05)),
                  np.full(n_groups, scipy.special.logit(max(np.mean(lens <= 2), 0.01)))]
        for name in post_params:
            blocks.append(blocks[GROUP_PARAMS.index(name)])
        blocks.append(np.zeros(n_ndt - 1))
        x0 = np.concatenate(blocks)

    limits = ([_LOG_POS_LIMITS] * 2 * n_groups + [_LOGIT_LIMITS] * 3 * n_groups)
    for name in post_params:
        limits += [_LOGIT_LIMITS if name == "guess_rate" else _LOG_POS_LIMITS] * n_groups
    limits += [_NDT_LOGIT_LIMITS] * (n_ndt - 1)

    def nll(theta):
        p, ndt_probs = _unpack(theta, n_groups, post_params, n_ndt)
        lik = _trial_likelihood(x, lens, choice_pm, group_idx, post_mask, p,
                                ndt_values, ndt_probs, wall=wall)
        return -np.sum(np.log(np.maximum(lik, _MIN_LIK)))

    res = scipy.optimize.minimize(nll, x0, method="L-BFGS-B", bounds=limits)
    p, ndt_probs = _unpack(res.x, n_groups, post_params, n_ndt)
    cols = list(GROUP_PARAMS) + [f"{name}_post" for name in post_params]
    table = pd.DataFrame({c: p[c] for c in cols})
    table.insert(0, "group", group_values)
    table["n_trials"] = np.bincount(group_idx, minlength=n_groups)
    # Post parameters are unconstrained for groups with no post-change-point positions.
    has_post = np.bincount(group_idx, weights=post_mask.any(axis=1), minlength=n_groups) > 0
    for name in post_params:
        table.loc[~has_post, f"{name}_post"] = np.nan
    return {
        "params": table,
        "ndt_probs": dict(zip(ndt_values, ndt_probs)),
        "nll": float(res.fun),
        "n_trials": int(len(lens)),
        "n_params": int(len(res.x)),
        "success": bool(res.success),
        "message": str(res.message),
        "theta": res.x,
    }


def simulate_stopping_trials(num_trials, generative_mean, generative_std, bound_mean, bound_std,
                             guess_rate=0.0, lapse_rate=0.0, anticipation_rate=0.0,
                             ndt_values=NDT_VALUES, ndt_probs=(1.0, 0.0, 0.0),
                             change_point=0, generative_mean_post=None, bound_mean_post=None,
                             bound_std_post=None, guess_rate_post=None,
                             max_steps=200, wall=WALL, rng=None):
    """
    Simulate trials from the stopping model (the generative model fit by fit_stopping_model).

    Parameters
    ----------
    num_trials : int
    generative_mean, generative_std : float
        Step mean magnitude (sign drawn 50/50 per trial) and SD.
    bound_mean, bound_std : float
        Mean and SD of the per-trial gamma bound distribution (position units).
    guess_rate, lapse_rate, anticipation_rate : float
        See module docstring.
    ndt_values, ndt_probs : sequences
        NDT support and probabilities.
    change_point : int or (num_trials,) array
        Position index from which post values apply (0 = no change point).
        As in the task, the step that produces position ``change_point`` is
        the first one drawn with ``generative_mean_post``.
    generative_mean_post, bound_mean_post, bound_std_post, guess_rate_post : float or None
        Post-change-point values (None = same as pre).
    max_steps : int
        Walk length; trials with no commit by ``max_steps - max(ndt_values) - 1``
        commit there (flagged ``commit_type = 'cap'``).
    wall : float
        Displayed positions are clamped to +/-wall, as in the task.
    rng : np.random.Generator or None

    Returns
    -------
    pd.DataFrame with get_data_table-style columns ``steps``, ``RT``, ``choice``
    (0/1), ``correct``, ``change_point``, ``wall_hit``, plus ground truth:
    ``commit_step``, ``ndt``, ``commit_type`` ('anticipation', 'bound',
    'guess', 'cap'), ``bound_pre`` (the trial's pre-change bound).
    """
    if rng is None:
        rng = np.random.default_rng()
    n = int(num_trials)
    post = lambda v, d: d if v is None else v  # noqa: E731
    gm_post = post(generative_mean_post, generative_mean)
    cp = np.broadcast_to(np.asarray(change_point, int), (n,))
    j = np.arange(max_steps + 1)[None, :]
    lpost = (cp[:, None] > 0) & (j >= cp[:, None])

    # Walk: the move producing position j is column j-1, so it uses the post mean when j >= cp.
    sgn = rng.choice([-1.0, 1.0], n)
    move_post = lpost[:, 1:]
    means = np.where(move_post, gm_post, generative_mean) * sgn[:, None]
    walk = np.concatenate([np.zeros((n, 1)), np.cumsum(rng.normal(means, generative_std), axis=1)], axis=1)
    shown = np.clip(walk, -wall, wall)
    ax = np.abs(shown)

    bm = np.where(lpost, post(bound_mean_post, bound_mean), bound_mean)
    bs = np.where(lpost, post(bound_std_post, bound_std), bound_std)
    gr = np.where(lpost, post(guess_rate_post, guess_rate), guess_rate)

    u = rng.random(n)
    f = _gamma_cdf(ax, bm, bs)
    f[:, 0] = 0.0
    hit_bound = f >= u[:, None]
    hit_guess = rng.random((n, max_steps + 1)) < gr
    hit_guess[:, 0] = False
    hit_bound[:, 0] = False

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
    side = np.sign(shown[rows, k])
    lapse = rng.random(n) < lapse_rate
    rand_side = rng.choice([-1.0, 1.0], n)
    choice = np.where(lapse | (side == 0), rand_side, side)
    rt = k + ndt + 1

    lant = rng.random(n) < anticipation_rate
    rt[lant] = rng.integers(1, ndt[lant] + 2)   # uniform over the first NDT + 1 frames
    choice[lant] = rand_side[lant]
    k[lant] = 0
    ctype[lant] = "anticipation"

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
        "bound_pre": _gamma_ppf(u, bound_mean, bound_std),
    })
