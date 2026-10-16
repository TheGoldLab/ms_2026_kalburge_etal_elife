"""Tests for pigeon.simulation."""

import numpy as np

from pigeon.simulation import BLOCK_DEFAULTS, get_simulated_data_table, simulate_trials


def test_ndt_is_drawn_from_the_given_range():
    choices, rts, DV, _, ndts, _, _ = simulate_trials(
        generative_mean=0.15, num_trials=5000, bound_mean=0.3, ndt_min=1, ndt_max=3, rng=np.random.default_rng(0)
    )
    assert set(np.unique(ndts)) == {1, 2, 3}
    crossing = np.argmax(np.abs(DV[:, :50]) >= 0.3, axis=1)
    lc = np.isfinite(choices) & (crossing + 4 <= 50)  # crossed, with room for any NDT
    np.testing.assert_array_equal(rts[lc], crossing[lc] + ndts[lc] + 1)  # RT = crossing step + NDT + 1


def test_per_snr_bounds_and_choices():
    choices, _, _, bounds, _, snrs, _ = simulate_trials(
        generative_mean=[0.05, 0.15], num_trials=4000, bound_mean=[0.2, 0.4], rng=np.random.default_rng(1)
    )
    np.testing.assert_array_equal(bounds[np.isclose(snrs, 1 / 3)], 0.2)
    np.testing.assert_array_equal(bounds[np.isclose(snrs, 1.0)], 0.4)
    assert np.nanmean(choices) > 0.7  # right is the correct side


def test_simulated_block_respects_step_budget_and_rewards():
    t = get_simulated_data_table(
        {"num_subjects": 3, "blocks": [2]}, generative_mean=0.05, bound_mean=0.2, rng=np.random.default_rng(2)
    )
    rules = BLOCK_DEFAULTS[2]
    for _, g in t.groupby("subject_index"):
        done = g[g.choice.notna()]
        assert done.RT.sum() <= rules["steps_per_block"]
        expected = rules["coins_gained"] * (done.choice == 1).sum() - rules["coins_lost"] * (done.choice == 0).sum()
        assert g.coin_count.iloc[-1] == expected


def test_ndt_probabilities_and_zero_ndt():
    _, _, _, _, ndts, _, _ = simulate_trials(
        generative_mean=0.15,
        num_trials=20000,
        bound_mean=0.3,
        ndt_min=1,
        ndt_max=2,
        ndt_probs=(0.7, 0.3),
        rng=np.random.default_rng(3),
    )
    assert abs(np.mean(ndts == 1) - 0.7) < 0.02
    choices, rts, DV, _, _, _, _ = simulate_trials(
        generative_mean=0.15, num_trials=2000, bound_mean=0.3, ndt_min=0, ndt_max=0, rng=np.random.default_rng(4)
    )
    lc = np.isfinite(choices)
    last = np.abs(DV[lc, rts[lc] - 1])  # the response comes at the crossing step
    assert np.all(last >= 0.3) and np.all(np.abs(DV[lc, np.maximum(rts[lc] - 2, 0)])[rts[lc] > 1] < 0.3)
