"""
Tests for pigeon.incentives: reward-rate moments of bound policies and their discriminability.

Deterministic walks (a tiny step SD) give known response times and outcomes, so the trial
accounting (RT including the start step, NDT, error costs, timeouts) is checked exactly; the
variance formula for a block's reward rate is checked against simulated blocks. Each test takes
well under a second.
"""

import numpy as np

from pigeon.incentives import get_reward_moments, get_reward_rate_dprime

PLAIN = {"coins_gained": 1, "coins_lost": 0, "steps_lost": 0}


def test_deterministic_walk_gives_the_known_response_time():
    # Steps of exactly 0.1 reach a bound of 0.25 at position 3; RT = 3 + NDT (1) + 1 start step.
    m = get_reward_moments(0.1, [0.25], 1e-9, [1.0], [PLAIN], num_trials=100, rng=np.random.default_rng(0))
    c, t, c2, ct, t2 = m[0, 0]
    assert (c, t, c2, ct, t2) == (1, 5, 1, 5, 25)


def test_errors_cost_coins_and_steps():
    # A walk to the left is always an error: -4 coins and 30 more steps.
    rules = [{"coins_gained": 1, "coins_lost": 4, "steps_lost": 30}]
    m = get_reward_moments(-0.1, [0.25], 1e-9, [0.0, 1.0], rules, num_trials=100, rng=np.random.default_rng(0))
    assert m[0, 0, 0] == -4
    assert m[0, 0, 1] == 3 + 2 + 1 + 30  # NDT 2


def test_unreached_bound_times_out_with_no_coins():
    m = get_reward_moments(0.01, [100.0], 1e-9, [1.0], [PLAIN], num_trials=100, max_steps=50)
    assert m[0, 0, 0] == 0 and m[0, 0, 1] == 50


def test_bound_sequence_follows_a_change_in_the_step_mean():
    # Mean 0.1 for steps 1-4 and 0.5 after; a bound of 10 until position 5 and 0.6 after: the
    # walk is at 0.4 at position 4 and 0.9 at position 5, where the bound is reached.
    means = np.r_[np.full(4, 0.1), np.full(45, 0.5)]
    bound = np.r_[np.full(4, 10.0), np.full(45, 0.6)]
    m = get_reward_moments(means, bound[None, :], 1e-9, [1.0], [PLAIN], num_trials=10)
    assert m[0, 0, 1] == 5 + 1 + 1


def test_dprime_is_zero_at_the_best_policy_and_grows_with_block_length():
    rng = np.random.default_rng(1)
    m = get_reward_moments(0.05, [0.05, 0.2, 0.5], 0.15, [0.6, 0.4], [PLAIN], num_trials=50_000, rng=rng)[0]
    rho, d1 = get_reward_rate_dprime(m, 600)
    _, d4 = get_reward_rate_dprime(m, 2400)
    assert d1[np.argmax(rho)] == 0 and np.all(d1 >= 0)
    np.testing.assert_allclose(d4, 2 * d1)


def test_block_variance_matches_simulated_blocks():
    # SD of the reward rate over 600-step blocks of simulated trials vs. the delta-method formula.
    rng = np.random.default_rng(2)
    steps_per_block = 600
    x = np.cumsum(rng.normal(0.05, 0.15, (400_000, 49)), axis=1)  # about 2000 blocks
    hit = np.abs(x) >= 0.3
    pos = hit.argmax(1) + 1
    t = np.where(hit.any(1), np.minimum(pos + 2, 50), 50)
    c = (hit.any(1) & (x[np.arange(len(x)), pos - 1] > 0)).astype(float)
    block = np.searchsorted(np.cumsum(t), np.arange(1, t.sum() // steps_per_block) * steps_per_block)
    rates = [cc.sum() / tt.sum() for cc, tt in zip(np.split(c, block), np.split(t, block))][:-1]
    m = get_reward_moments(0.05, [0.3], 0.15, [1.0], [PLAIN], num_trials=200_000, rng=rng)[0]
    rho = m[0, 0] / m[0, 1]
    var = (m[0, 2] - 2 * rho * m[0, 3] + rho**2 * m[0, 4]) / (steps_per_block * m[0, 1])
    np.testing.assert_allclose(np.std(rates), np.sqrt(var), rtol=0.08)
