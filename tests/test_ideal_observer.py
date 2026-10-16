"""Tests for pigeon.ideal_observer (reward-rate-optimal bounds by dynamic programming)."""

import numpy as np

from pigeon.ideal_observer import MAX_STEPS, get_optimal_bounds

LOW, HIGH = (1, 1), (3, 3)


def _simulated_reward_rate(
    bound, reward_pre, reward_post, switch_step, mu=0.01, sigma=0.05, start_cost=5, error_cost=10, n=200_000, seed=0
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
    rho1, b1 = get_optimal_bounds(LOW)
    rho3, b3 = get_optimal_bounds(HIGH)
    np.testing.assert_allclose(b3, b1)
    np.testing.assert_allclose(rho3, 3 * rho1, rtol=1e-6)


def test_rising_reward_waits_out_the_switch_and_falling_reward_rushes_it():
    sw = 9
    _, fixed = get_optimal_bounds(LOW)
    _, rising = get_optimal_bounds(LOW, HIGH, sw)
    _, falling = get_optimal_bounds(HIGH, LOW, sw)
    assert np.isnan(rising[:sw]).all() and np.isfinite(rising[sw:]).all()
    assert falling[sw - 1] < 0.5 * fixed[sw - 1]  # bound collapses just before the reward drops
    assert np.nanmedian(falling[sw : sw + 20]) < fixed[sw]  # and stays low after it


def test_dynamic_programming_reward_rate_matches_simulation():
    for pre, post, sw in ((LOW, LOW, MAX_STEPS), (LOW, HIGH, 9), (HIGH, LOW, 9)):
        rho, bound = get_optimal_bounds(pre, post, sw)
        np.testing.assert_allclose(_simulated_reward_rate(bound, pre, post, sw), rho, rtol=0.03)


def test_optimal_policy_beats_nearby_flat_bounds():
    rho, bound = get_optimal_bounds(LOW)
    for scale in (0.7, 1.4):
        assert _simulated_reward_rate(np.full(MAX_STEPS, scale * bound[5]), LOW, LOW, MAX_STEPS) < rho


def test_larger_trial_cost_raises_the_bound():
    _, cheap = get_optimal_bounds(LOW, start_cost=1, error_cost=0)
    _, costly = get_optimal_bounds(LOW, start_cost=20, error_cost=10)
    assert costly[5] > cheap[5]
