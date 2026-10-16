"""
Reward-rate-optimal (ideal-observer) bounds for the pigeon task, by dynamic programming.

Used to design the RC (reward change) task (task/RC; notebooks/Test_cpRDesign.ipynb):
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
