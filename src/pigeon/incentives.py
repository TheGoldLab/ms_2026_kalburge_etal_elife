"""
Reward-rate incentives: how well a participant could tell a bound policy from the best one (Figure 8).

Question
--------
For a block with a given step budget and reward rules, how much does the reward rate
depend on the bound, relative to the block-to-block noise in the reward rate a
participant actually experiences? A policy whose reward rate cannot be told from the
best one's within a block gives the participant no usable signal to move away from it.

Simulation (``get_reward_moments``)
-----------------------------------
An ideal participant: no sensory noise, no trial-to-trial bound variability, guesses
or lapses. Each trial is a 1-D random walk with a known mean at each step (positive:
right is correct); the participant responds at the first position j >= 1 at which
|x_j| >= theta_j (theta is the policy: a flat bound, or any bound sequence over the
trial), choosing the side x_j is on. The trial accounting is simulate_trials's: the
response comes NDT steps later (NDT drawn from ``ndt_probs``, limited so the trial
fits in ``max_steps``), the trial costs RT = j + NDT + 1 steps (including the
trial-start step), and a trial that never reaches the bound ends at ``max_steps``
with no choice and no coins. A correct choice earns ``coins_gained``; an error loses
``coins_lost`` coins and costs ``steps_lost`` more steps. The bound walls of the task
(+/-0.75 in the online task) are ignored, as in Figures 4 and 5.

Every policy is applied to the same simulated walks, so differences between policies
are much more precise than each policy's reward rate on its own. The result is, per
policy, the first and second moments of a trial's coins c and steps t:
E[c], E[t], E[c^2], E[ct], E[t^2]. Moments are linear in the trial mixture, so the
moments of a block that interleaves trial types (e.g. two SNRs, half each) are the
weighted average of the types' moments.

Reward rate and discriminability (``get_reward_rate_dprime``)
--------------------------------------------------------------
By renewal-reward, the long-run reward rate is rho = E[c] / E[t] (coins per step).
Over a block of S steps (about S / E[t] trials) the measured reward rate is
approximately normal with variance

    Var(rho_hat) = E[(c - rho t)^2] / (S E[t]),

the delta-method variance of a ratio of sums. Comparing a policy with the best one,
each played for one block,

    d' = (rho_best - rho) / sqrt(Var_best + Var),

so the better policy comes out ahead in a fraction Phi(d') of such comparisons.
d' grows with the square root of experience, so 1 / d'^2 is the number of blocks of
each policy needed to reach d' = 1 (Figure 8's color scale).
"""

from __future__ import annotations

import numpy as np

MOMENT_NAMES = ("c", "t", "c2", "ct", "t2")  # order of the last axis of the moments


def get_reward_moments(
    step_means,
    bounds,
    step_std,
    ndt_probs,
    rules,
    num_trials: int = 200_000,
    max_steps: int = 50,
    rng=None,
) -> np.ndarray:
    """
    Per-trial coin and step moments of bound policies, by simulation (ideal participant).

    Parameters
    ----------
    step_means : float or (max_steps - 1,) array
        Mean of each step (step j produces position j); positive means right is correct.
        An array gives a mean that changes within the trial (a change point).
    bounds : (n_policies,) or (n_policies, max_steps - 1) array
        Flat bounds, or a bound at each position 1..max_steps - 1 per policy.
    step_std : float
        SD of each step.
    ndt_probs : sequence of float
        Probabilities of a non-decision time of 1, 2, ... steps.
    rules : sequence of dict
        Reward rules (keys ``coins_gained``, ``coins_lost``, ``steps_lost``, as in
        pigeon.simulation.BLOCK_DEFAULTS); all are scored on the same trials.
    num_trials : int
        Simulated trials, shared by all policies and rules.
    max_steps : int
        Trial length (steps); a trial still running ends with no choice.
    rng : np.random.Generator or None

    Returns
    -------
    (n_rules, n_policies, 5) array
        E[c], E[t], E[c^2], E[ct], E[t^2] per rule and policy (coins c and steps t of a
        trial; order MOMENT_NAMES).
    """
    if rng is None:
        rng = np.random.default_rng()
    n_pos = max_steps - 1  # positions 1..max_steps - 1 can trigger a response (simulate_trials)
    means = np.broadcast_to(np.asarray(step_means, float), (n_pos,))
    bounds = np.asarray(bounds, float)
    if bounds.ndim == 1:
        bounds = np.repeat(bounds[:, None], n_pos, axis=1)
    if bounds.shape[1] != n_pos:
        raise ValueError(f"bounds must have {n_pos} positions per policy, not {bounds.shape[1]}.")
    ndt_probs = np.asarray(ndt_probs, float)
    x = np.cumsum(rng.normal(means, step_std, (num_trials, n_pos)), axis=1)
    abs_x = np.abs(x).astype(np.float32)
    right = x > 0
    ndt = rng.choice(np.arange(1, len(ndt_probs) + 1), size=num_trials, p=ndt_probs / ndt_probs.sum())
    rows = np.arange(num_trials)

    out = np.empty((len(rules), len(bounds), 5))
    for pi, theta in enumerate(bounds.astype(np.float32)):
        crossed = abs_x >= theta
        hit = crossed.any(axis=1)
        pos = crossed.argmax(axis=1) + 1  # first position at the bound (meaningful where hit)
        rt = np.where(hit, np.minimum(pos + ndt + 1, max_steps), max_steps)
        correct = hit & right[rows, pos - 1]
        error = hit & ~correct
        for ri, r in enumerate(rules):
            c = r["coins_gained"] * correct - r["coins_lost"] * error
            t = rt + r["steps_lost"] * error
            out[ri, pi] = c.mean(), t.mean(), (c * c).mean(), (c * t).mean(), (t * t.astype(float)).mean()
    return out


def get_reward_rate_dprime(moments, steps_per_block: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Reward rate of each policy and its discriminability from the best one within one block.

    Parameters
    ----------
    moments : (..., 5) array
        Output of get_reward_moments (or a mixture of outputs) over any grid of policies.
    steps_per_block : int
        Step budget of a block.

    Returns
    -------
    rho : (...) array
        Reward rate, coins per step.
    dprime : (...) array
        (rho_best - rho) / sqrt(Var_best + Var), with Var the variance of one block's
        measured reward rate; 0 at the best policy (over the whole grid).
    """
    c, t, c2, ct, t2 = np.moveaxis(np.asarray(moments, float), -1, 0)
    rho = c / t
    var = (c2 - 2 * rho * ct + rho**2 * t2) / (steps_per_block * t)
    i_best = np.unravel_index(np.argmax(rho), rho.shape)
    return rho, (rho[i_best] - rho) / np.sqrt(var[i_best] + var)
