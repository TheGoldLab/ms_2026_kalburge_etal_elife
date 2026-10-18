"""
Reward-rate-optimal (ideal-observer) bounds for the pigeon task, by dynamic programming.

Used to design the RC (reward change) task (task/RC; notebooks/Design_rcTask.ipynb):
which bound, step by step within a trial, maximizes coins per step in a step-budgeted
block whose reward may switch at a fixed step of every trial.

Observer
--------
Sees Petey's exact position x_t (no sensory noise), knows the step mean ``mu`` and SD
``sigma`` but not the direction (left/right equally likely), so after any path ending
at x_t

    P(the correct pile is right | x_t) = 1 / (1 + exp(-2 mu x_t / sigma^2)),

and x_t is a sufficient statistic. At each shown position t = 0..max_steps-1 it either
responds now (choosing the likelier side) or waits one more step; at t = max_steps the
trial times out (no choice, no coins). There is no non-decision time, and the wall at
+/-0.75 is ignored (the optimal bounds stay well inside it).

Rewards and costs
-----------------
A response made while position t is shown earns ``reward_pre`` = (gain, loss) if
t < switch_step and ``reward_post`` otherwise, the task's rule (a response is scored
with the coin values in force on the step it is made). Costs are in steps: one per
waited step, ``start_cost`` per trial, ``error_cost`` more after an error.

Objective
---------
A block is a step budget, so the objective is the long-run reward rate rho (coins per
step). By renewal-reward, rho is the rate at which a new trial is worth exactly nothing
once every step is charged rho: backward induction on V_t(x) = max(respond, wait) with

    respond_t(x) = g_t P_c(x) - (l_t + rho * error_cost) (1 - P_c(x)),
    wait_t(x)    = -rho + E[V_{t+1}(x') | x],

V_{max_steps} = 0, and rho found by bisection so that V_0(0) = rho * start_cost. The
optimal bound at step t is the smallest |x| at which responding is at least as good as
waiting (NaN where waiting is better at every position).

Transitions use a fixed position grid with the predictive step density (a mixture of
N(+mu, sigma) and N(-mu, sigma) weighted by the posterior), renormalized per row.

Mixtures of step means (``get_optimal_bounds_mixture``)
-------------------------------------------------------
For trials whose step mean is drawn from a known set {mu_k} (with probabilities w_k, each
direction equally likely; mu = 0 allowed, its correct side a coin flip), the posterior
after t steps ending at x is

    P(mu_k, +/- | x, t) proportional to w_k exp((+/- mu_k x - mu_k^2 t / 2) / sigma^2),

so it depends on (x, t), and the optimal policy is a bound that may change with t.
The predictive density of the next step mixes fixed Gaussian kernels N(+/- mu_k, sigma)
with these weights, so E[V_{t+1}(x') | x, t] needs only one product per signed mean.
Costs are those of Figure05S02's simulation: rho per waited step (the opportunity cost
of time; no other cost per step), ``start_cost`` steps per trial (the trial start plus
the mean non-decision time), ``error_cost`` more after an error; a trial still running
at ``max_steps`` ends with a forced response (the likelier side). ``evaluate_bound``
gives the reward rate of any given bound sequence with the same machinery, so the
optimal policy can be compared exactly with, e.g., the best flat bound
(``get_best_flat_bound``).
"""

from __future__ import annotations

import numpy as np
import scipy.stats

RC_STEP_MEAN = 0.01  # RC task: one difficulty for every block (MXSC's low SNR)
RC_STEP_STD = 0.05
RC_START_COST = 5  # steps charged to start each trial
RC_ERROR_COST = 10  # extra steps charged per error
MAX_STEPS = 50  # trial length (timeout) in the task
X_HALF_WIDTH, X_POINTS = 1.2, 1201


def _transition(x, mu, sigma):
    """Row-stochastic matrix of P(x' | x) on the grid, mixing the two drift directions by the posterior."""
    dx = x[1] - x[0]
    p_right = 1 / (1 + np.exp(-2 * mu * x / sigma**2))
    off = x[None, :] - x[:, None]
    trans = (
        p_right[:, None] * scipy.stats.norm.pdf(off, mu, sigma)
        + (1 - p_right)[:, None] * scipy.stats.norm.pdf(off, -mu, sigma)
    ) * dx
    return trans / trans.sum(1, keepdims=True), np.maximum(p_right, 1 - p_right)


def _backward_induction(rho, p_correct, trans, reward_pre, reward_post, switch_step, error_cost, max_steps):
    """Value of a new trial at x = 0 (before the start cost) and the stop mask, for one reward rate rho."""
    v = np.zeros(p_correct.size)  # t = max_steps: timeout, no coins
    stop = np.zeros((max_steps, p_correct.size), bool)
    for tt in range(max_steps - 1, -1, -1):
        gain, loss = reward_post if tt >= switch_step else reward_pre
        respond = gain * p_correct - (loss + rho * error_cost) * (1 - p_correct)
        wait = -rho + trans @ v
        stop[tt] = respond >= wait
        v = np.maximum(respond, wait)
    return v[p_correct.size // 2], stop


def get_optimal_bounds(
    reward_pre: tuple[float, float],
    reward_post: tuple[float, float] | None = None,
    switch_step: int | None = None,
    step_mean: float = RC_STEP_MEAN,
    step_std: float = RC_STEP_STD,
    start_cost: float = RC_START_COST,
    error_cost: float = RC_ERROR_COST,
    max_steps: int = MAX_STEPS,
    n_bisect: int = 60,
) -> tuple[float, np.ndarray]:
    """
    Reward-rate-maximizing bound at each step of a trial (see module docstring).

    Parameters
    ----------
    reward_pre : (gain, loss)
        Coins gained for a correct response and lost for an error before the switch.
    reward_post : (gain, loss) or None
        The same from ``switch_step`` on; None = no switch (``reward_pre`` throughout).
    switch_step : int or None
        First shown position index that earns ``reward_post``; None = no switch.
    step_mean, step_std : float
        Magnitude of Petey's step mean (direction unknown) and its SD, in screen units.
    start_cost, error_cost : float
        Steps charged to start each trial and, additionally, after each error.
    max_steps : int
        Trial length; a trial with no response by then times out with no coins.
    n_bisect : int
        Bisection iterations on the reward rate (60 halvings: machine precision).

    Returns
    -------
    rho : float
        Optimal reward rate, coins per step.
    bound : (max_steps,) array
        Optimal bound (|position| at which to respond) at shown positions 0..max_steps-1,
        NaN where waiting is optimal at every position.
    """
    if reward_post is None or switch_step is None:
        reward_post, switch_step = reward_pre, max_steps
    x = np.linspace(-X_HALF_WIDTH, X_HALF_WIDTH, X_POINTS)
    trans, p_correct = _transition(x, step_mean, step_std)
    args = (p_correct, trans, reward_pre, reward_post, switch_step, error_cost, max_steps)
    lo, hi = 0.0, float(max(reward_pre[0], reward_post[0]))  # rho can't exceed the largest gain per step
    for _ in range(n_bisect):
        rho = (lo + hi) / 2
        v0, _ = _backward_induction(rho, *args)
        lo, hi = (rho, hi) if v0 - rho * start_cost > 0 else (lo, rho)
    _, stop = _backward_induction(rho, *args)
    right = x >= 0
    bound = np.array([x[right][s[right]].min() if s[right].any() else np.nan for s in stop])
    return rho, bound


# Mixtures of step means (zero-SNR trials allowed); defaults are Figure05S02's task.
MIX_STEP_STD = 0.15
MIX_MAX_STEPS = 300
MIX_X_HALF_WIDTH, MIX_DX = 4.0, 0.01


class _MixtureModel:
    """Grid, kernels and per-step posterior quantities for a mixture of step means."""

    def __init__(self, step_means, weights, step_std, max_steps, x_half_width, dx):
        means = np.asarray(step_means, float)
        w = np.asarray(weights, float)
        if means.shape != w.shape or np.any(means < 0) or np.any(w < 0):
            raise ValueError("step_means and weights must be non-negative and the same length.")
        w = w / w.sum()
        # integer multiples of dx, so x = 0 is on the grid exactly (a bound of 0: respond at once)
        n_half = round(x_half_width / dx)
        self.x = dx * np.arange(-n_half, n_half + 1)
        self.max_steps = max_steps
        # Signed means: (+mu, weight w/2) and (-mu, w/2); mu = 0 once with weight w.
        signed, sw = [], []
        for mu, wk in zip(means, w):
            if mu == 0:
                signed.append(0.0)
                sw.append(wk)
            else:
                signed += [mu, -mu]
                sw += [wk / 2, wk / 2]
        self.signed = np.array(signed)
        self.sw = np.array(sw)
        off = self.x[None, :] - self.x[:, None]
        self.kernels = []
        for m in self.signed:
            k = scipy.stats.norm.pdf(off, m, step_std)
            self.kernels.append(k / k.sum(1, keepdims=True))  # renormalized: mass beyond the grid edge
        self.var = step_std**2
        self.post = np.stack([self.posterior(t) for t in range(max_steps + 1)])
        self.pc = np.stack([self.p_correct(p) for p in self.post])

    def posterior(self, t):
        """(n_signed, n_x) posterior over signed means after t steps, at each grid position."""
        logp = (
            np.log(np.maximum(self.sw, 1e-300))[:, None]
            + (self.signed[:, None] * self.x[None, :] - 0.5 * self.signed[:, None] ** 2 * t) / self.var
        )
        logp -= logp.max(0, keepdims=True)
        p = np.exp(logp)
        return p / p.sum(0, keepdims=True)

    def p_correct(self, post):
        """P(the likelier side is correct): mu > 0 favors right, mu < 0 left, mu = 0 is a coin flip."""
        right = post[self.signed > 0].sum(0) + 0.5 * post[self.signed == 0].sum(0)
        return np.maximum(right, 1 - right)


def _mixture_values(model, rho, gain, loss, error_cost, bound=None):
    """
    Backward induction for one reward rate rho: value of a new trial at x = 0 (before the start
    cost) and the stop mask. With ``bound`` given, the policy is fixed (respond when |x| >= bound[t]).
    """
    n = model.x.size
    stop = np.ones((model.max_steps + 1, n), bool)  # forced response at max_steps
    v = gain * model.pc[-1] - (loss + rho * error_cost) * (1 - model.pc[-1])
    for tt in range(model.max_steps - 1, -1, -1):
        pc = model.pc[tt]
        respond = gain * pc - (loss + rho * error_cost) * (1 - pc)
        wait = -rho + sum(p * (k @ v) for p, k in zip(model.post[tt], model.kernels))
        s = respond >= wait if bound is None else np.abs(model.x) >= bound[tt]
        if tt == 0:
            s = np.zeros(n, bool)  # no response before the first step
        stop[tt] = s
        v = np.where(s, respond, wait)
    return v[n // 2], stop


def _solve_rho(model, gain, loss, error_cost, start_cost, bound=None, n_bisect=45):
    lo, hi = -float(loss) - 1e-9, float(gain)  # a fixed policy can lose coins on average
    for _ in range(n_bisect):
        rho = (lo + hi) / 2
        v0, _ = _mixture_values(model, rho, gain, loss, error_cost, bound)
        lo, hi = (rho, hi) if v0 - rho * start_cost > 0 else (lo, rho)
    return (lo + hi) / 2


def get_optimal_bounds_mixture(
    step_means,
    weights,
    gain: float = 1.0,
    loss: float = 0.0,
    error_cost: float = 0.0,
    start_cost: float = 1.0,
    step_std: float = MIX_STEP_STD,
    max_steps: int = MIX_MAX_STEPS,
    x_half_width: float = MIX_X_HALF_WIDTH,
    dx: float = MIX_DX,
) -> tuple[float, np.ndarray]:
    """
    Reward-rate-optimal bound at each step when the step mean is drawn from a mixture.

    Parameters
    ----------
    step_means, weights : sequences of float
        Magnitudes of the possible step means (0 allowed: zero-SNR trials) and their
        probabilities (normalized); each direction is equally likely.
    gain, loss : float
        Coins gained for a correct response and lost for an error.
    error_cost : float
        Extra steps charged after an error (the step penalty).
    start_cost : float
        Steps charged per trial besides the decision steps: the trial start (1 in the task)
        plus the mean non-decision time.
    step_std : float
        SD of each step, in screen units.
    max_steps : int
        Steps after which the observer must respond.
    x_half_width, dx : float
        Position grid (screen units).

    Returns
    -------
    rho : float
        Optimal reward rate, coins per step.
    bound : (max_steps + 1,) array
        Optimal bound (|position| at which to respond) at steps 0..max_steps; NaN where
        waiting is optimal at every position on the grid (always at step 0).
    """
    model = _MixtureModel(step_means, weights, step_std, max_steps, x_half_width, dx)
    rho = _solve_rho(model, gain, loss, error_cost, start_cost)
    _, stop = _mixture_values(model, rho, gain, loss, error_cost)
    right = model.x >= 0
    bound = np.array([model.x[right][s[right]].min() if s[right].any() else np.nan for s in stop])
    return rho, bound


def evaluate_bound(
    bound,
    step_means,
    weights,
    gain: float = 1.0,
    loss: float = 0.0,
    error_cost: float = 0.0,
    start_cost: float = 1.0,
    step_std: float = MIX_STEP_STD,
    max_steps: int = MIX_MAX_STEPS,
    x_half_width: float = MIX_X_HALF_WIDTH,
    dx: float = MIX_DX,
) -> float:
    """
    Reward rate (coins per step) of responding at the first step t >= 1 with |x| >= bound[t]
    (forced response at ``max_steps``), on the same grid and rules as get_optimal_bounds_mixture.

    ``bound`` is a scalar (flat bound) or an array over steps 0..max_steps (step 0 is ignored:
    no response before the first step).
    """
    model = _MixtureModel(step_means, weights, step_std, max_steps, x_half_width, dx)
    b = np.broadcast_to(np.asarray(bound, float), (max_steps + 1,)).copy()
    b[0] = np.inf
    return _solve_rho(model, gain, loss, error_cost, start_cost, bound=b)


def get_best_flat_bound(
    step_means,
    weights,
    gain: float = 1.0,
    loss: float = 0.0,
    error_cost: float = 0.0,
    start_cost: float = 1.0,
    step_std: float = MIX_STEP_STD,
    max_steps: int = MIX_MAX_STEPS,
    x_half_width: float = MIX_X_HALF_WIDTH,
    dx: float = MIX_DX,
    bound_min: float = 0.0,
    bound_max: float = 1.2,
    n_coarse: int = 13,
    n_golden: int = 16,
) -> tuple[float, float]:
    """
    Best flat bound and its reward rate, on the same grid and rules as get_optimal_bounds_mixture.

    A coarse scan of ``n_coarse`` bounds between ``bound_min`` and ``bound_max`` brackets the
    best one, and ``n_golden`` golden-section steps refine it within the neighboring scan
    points (the reward rate of a flat bound is unimodal in the cases checked; the scan guards
    against a poor bracket).

    Returns
    -------
    bound : float
        Best flat bound (|position|).
    rho : float
        Its reward rate, coins per step.
    """
    model = _MixtureModel(step_means, weights, step_std, max_steps, x_half_width, dx)

    def rate(b):
        seq = np.full(max_steps + 1, b)
        seq[0] = np.inf
        return _solve_rho(model, gain, loss, error_cost, start_cost, bound=seq)

    grid = np.linspace(bound_min, bound_max, n_coarse)
    rates = np.array([rate(b) for b in grid])
    i = int(np.argmax(rates))
    lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, n_coarse - 1)]
    g = (np.sqrt(5) - 1) / 2
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    f1, f2 = rate(x1), rate(x2)
    for _ in range(n_golden):
        if f1 < f2:
            lo, x1, f1 = x1, x2, f2
            x2 = lo + g * (hi - lo)
            f2 = rate(x2)
        else:
            hi, x2, f2 = x2, x1, f1
            x1 = hi - g * (hi - lo)
            f1 = rate(x1)
    best = max([(rates[i], grid[i]), (f1, x1), (f2, x2)])
    return float(best[1]), float(best[0])
