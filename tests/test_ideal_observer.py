"""
Tests for pigeon.ideal_observer: reward-rate-optimal bounds by dynamic programming.

The solver's answers are checked against properties that must hold (scaling both gain and loss
leaves the policy unchanged; a larger trial cost raises the bound; the policy beats nearby flat
bounds) and against a Monte Carlo simulation of the same task rules. Each test takes a few seconds.
"""

import numpy as np

from pigeon.ideal_observer import (
    MAX_STEPS,
    RC_ERROR_COST,
    RC_START_COST,
    evaluate_bound,
    evaluate_rc_bound,
    get_best_flat_bound,
    get_fixed_time_accuracy,
    get_optimal_bounds,
    get_optimal_bounds_mixture,
    get_rc_policy_outcomes,
)

LOW, HIGH = (1, 1), (3, 3)


def _simulated_reward_rate(
    bound,
    reward_pre,
    reward_post,
    switch_step,
    mu=0.01,
    sigma=0.05,
    start_cost=RC_START_COST,
    error_cost=RC_ERROR_COST,
    n=200_000,
    seed=0,
):
    """Monte Carlo coins per step of a given bound policy under the task's rules (drift to the right)."""
    rng = np.random.default_rng(seed)
    x = np.concatenate([np.zeros((n, 1)), np.cumsum(rng.normal(mu, sigma, (n, MAX_STEPS - 1)), axis=1)], axis=1)
    b = np.where(np.isnan(bound), np.inf, bound)
    hit = np.abs(x) >= b[None, :]
    responded = hit.any(1)
    tt = hit.argmax(1)
    correct = x[np.arange(n), tt] > 0
    gain = np.where(tt >= switch_step, reward_post[0], reward_pre[0])
    loss = np.where(tt >= switch_step, reward_post[1], reward_pre[1])
    coins = np.where(responded, np.where(correct, gain, -loss), 0)
    steps = np.where(responded, tt, MAX_STEPS) + start_cost + error_cost * (responded & ~correct)
    return coins.sum() / steps.sum()


def test_scaling_gain_and_loss_leaves_the_policy_unchanged():
    """Tripling both gain and loss triples the reward rate but leaves the optimal bounds unchanged."""
    rho1, b1 = get_optimal_bounds(LOW)
    rho3, b3 = get_optimal_bounds(HIGH)
    np.testing.assert_allclose(b3, b1)
    np.testing.assert_allclose(rho3, 3 * rho1, rtol=1e-6)


def test_rising_reward_waits_out_the_switch_and_falling_reward_rushes_it():
    """
    With rising reward the optimal policy never responds before the switch; with falling reward the bound
    collapses just before it and stays low after.
    """
    sw = 9
    _, fixed = get_optimal_bounds(LOW)
    _, rising = get_optimal_bounds(LOW, HIGH, sw)
    _, falling = get_optimal_bounds(HIGH, LOW, sw)
    assert np.isnan(rising[:sw]).all() and np.isfinite(rising[sw:]).all()
    assert falling[sw - 1] < 0.5 * fixed[sw - 1]  # bound collapses just before the reward drops
    assert np.nanmedian(falling[sw : sw + 20]) < fixed[sw]  # and stays low after it


def test_dynamic_programming_reward_rate_matches_simulation():
    """The reward rate the solver reports matches a Monte Carlo simulation of its own policy within 3%."""
    for pre, post, sw in ((LOW, LOW, MAX_STEPS), (LOW, HIGH, 9), (HIGH, LOW, 9)):
        rho, bound = get_optimal_bounds(pre, post, sw)
        np.testing.assert_allclose(_simulated_reward_rate(bound, pre, post, sw), rho, rtol=0.03)


def test_optimal_policy_beats_nearby_flat_bounds():
    """Flat bounds 30% lower or 40% higher than the optimal bound earn less."""
    rho, bound = get_optimal_bounds(LOW)
    for scale in (0.7, 1.4):
        assert _simulated_reward_rate(np.full(MAX_STEPS, scale * bound[5]), LOW, LOW, MAX_STEPS) < rho


def test_rc_bound_evaluation_matches_the_optimum_and_simulation():
    """
    evaluate_rc_bound gives the optimal policy the solver's reward rate, and a flat bound (a policy the
    solver did not choose) the Monte Carlo reward rate within 3%, in a fixed and a falling-reward block.
    """
    rho, bound = get_optimal_bounds(HIGH, LOW, 9)
    np.testing.assert_allclose(evaluate_rc_bound(bound, HIGH, LOW, 9), rho, rtol=1e-6)
    for pre, post, sw in ((LOW, LOW, MAX_STEPS), (HIGH, LOW, 9)):
        flat = np.full(MAX_STEPS, 0.2)
        np.testing.assert_allclose(
            evaluate_rc_bound(flat, pre, post, sw), _simulated_reward_rate(flat, pre, post, sw), rtol=0.03
        )


def test_rc_policy_outcomes_match_simulation():
    """Accuracy and trials per 1000-step block of a flat bound match a Monte Carlo simulation of the task rules."""
    bound, n = 0.15, 200_000
    out = get_rc_policy_outcomes(bound)
    rng = np.random.default_rng(1)
    x = np.concatenate([np.zeros((n, 1)), np.cumsum(rng.normal(0.01, 0.05, (n, MAX_STEPS - 1)), axis=1)], axis=1)
    hit = np.abs(x) >= bound
    responded = hit.any(1)
    tt = hit.argmax(1)
    correct = responded & (x[np.arange(n), tt] > 0)
    steps = np.where(responded, tt, MAX_STEPS) + RC_START_COST + RC_ERROR_COST * (responded & ~correct)
    np.testing.assert_allclose(out["accuracy"], correct.sum() / responded.sum(), atol=0.01)
    np.testing.assert_allclose(out["trials_per_block"], 1000 / steps.mean(), rtol=0.02)


def test_larger_trial_cost_raises_the_bound():
    """Raising the cost of starting a trial and of an error raises the optimal bound."""
    _, cheap = get_optimal_bounds(LOW, start_cost=1, error_cost=0)
    _, costly = get_optimal_bounds(LOW, start_cost=20, error_cost=10)
    assert costly[5] > cheap[5]


def _simulated_mixture_rate(bound, means, loss, error_cost, start_cost, max_steps, n=120_000, seed=0):
    """Monte Carlo coins per step of a bound sequence over a mixture of step means (SD 0.15; mu = 0: coin flip)."""
    rng = np.random.default_rng(seed)
    coins = steps = 0.0
    b = np.where(np.isnan(bound), np.inf, bound)
    b[0] = np.inf
    for mu in means:
        k = n // len(means)
        x = np.concatenate([np.zeros((k, 1)), np.cumsum(rng.normal(mu, 0.15, (k, max_steps)), axis=1)], axis=1)
        hit = np.abs(x) >= b[None, :]
        hit[:, -1] = True  # forced response at max_steps
        tt = hit.argmax(1)
        correct = x[np.arange(k), tt] > 0 if mu > 0 else rng.random(k) < 0.5
        coins += np.where(correct, 1, -loss).sum()
        steps += (tt + start_cost + error_cost * ~correct).sum()
    return coins / steps


def test_mixture_with_one_step_mean_matches_the_single_mean_solver():
    """With a single step mean the mixture solver gives the same reward rate as get_optimal_bounds, and a flat bound."""
    rho, bound = get_optimal_bounds_mixture([0.05], [1], loss=4, start_cost=1, max_steps=120)
    rho_1, _ = get_optimal_bounds((1, 4), step_mean=0.05, step_std=0.15, start_cost=1, error_cost=0, max_steps=120)
    np.testing.assert_allclose(rho, rho_1, rtol=1e-3)
    assert np.ptp(bound[1:100]) <= 0.02  # flat up to the grid spacing (0.01), away from the forced response


def test_mixture_reward_rate_matches_simulation_with_zero_snr_trials():
    """The reward rate the mixture solver reports is what its policy earns in simulation, with zero-SNR trials mixed in."""
    means = [0.0, 0.05, 0.15]
    rho, bound = get_optimal_bounds_mixture(means, [1, 1, 1], error_cost=30, start_cost=2.4, max_steps=120)
    np.testing.assert_allclose(_simulated_mixture_rate(bound, means, 0, 30, 2.4, 120), rho, rtol=0.03)


def test_evaluate_bound_never_beats_the_optimal_policy():
    """Evaluating the optimal bound as a fixed policy returns the optimal reward rate; a flat bound earns less."""
    args = ([0.0, 0.05, 0.15], [1, 1, 1])
    kw = {"error_cost": 30, "start_cost": 2.4, "max_steps": 60}
    rho, bound = get_optimal_bounds_mixture(*args, **kw)
    np.testing.assert_allclose(evaluate_bound(np.nan_to_num(bound, nan=np.inf), *args, **kw), rho, rtol=1e-4)
    assert evaluate_bound(0.2, *args, **kw) < rho


def test_best_flat_bound_beats_its_neighbors_and_matches_the_optimum_without_zero_snr():
    """The best flat bound earns more than bounds 20% lower or higher, and with one step mean it matches the optimal policy."""
    args, kw = ([0.15], [1]), {"loss": 4, "start_cost": 2.4, "max_steps": 120}
    b, rho = get_best_flat_bound(*args, **kw)
    assert rho > evaluate_bound(0.8 * b, *args, **kw)
    assert rho > evaluate_bound(1.2 * b, *args, **kw)
    rho_opt, _ = get_optimal_bounds_mixture(*args, **kw)
    assert rho <= rho_opt + 1e-9
    np.testing.assert_allclose(rho, rho_opt, rtol=1e-3)


def test_fixed_time_accuracy():
    """Phi(mu sqrt(n) / sigma): the paper's 77%/99% (cohorts 1, 2) and 67%/91% (cohort 3) after 5 steps."""
    acc = get_fixed_time_accuracy(np.array([0.05, 0.15, 0.01, 0.03]), np.array([0.15, 0.15, 0.05, 0.05]), 5)
    assert np.allclose(np.round(100 * acc), [77, 99, 67, 91])
    assert get_fixed_time_accuracy(0.0, 0.15, 5) == 0.5
