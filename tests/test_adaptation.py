"""Tests for pigeon.adaptation."""

import numpy as np
import pandas as pd

from pigeon.adaptation import (
    between_block_significance,
    compute_per_subject_curves_with_nulls,
    get_post_error_bound_effect,
    get_sequential_bound_stats,
)


def test_sequential_bound_stats_independent_vs_autocorrelated():
    rng = np.random.default_rng(0)
    n = 4000
    iid = rng.normal(0.4, 0.1, n)
    ar = np.empty(n)
    ar[0] = 0.4
    for i in range(1, n):  # AR(1) with coefficient 0.6 around 0.4
        ar[i] = 0.4 + 0.6 * (ar[i - 1] - 0.4) + rng.normal(0, 0.08)
    # Rows shuffled: the statistics must order trials by trial_number, not by row.
    d = pd.concat(
        [
            pd.DataFrame({"subject_index": s, "block_index": 1, "trial_number": np.arange(n), "abs_bound": v})
            for s, v in ((1, iid), (2, ar))
        ]
    ).sample(frac=1, random_state=1)
    st = get_sequential_bound_stats(d)
    assert abs(st.loc[(1, 1), "delta_slope"] + 1) < 0.05 and abs(st.loc[(1, 1), "lag1_r"]) < 0.05
    assert abs(st.loc[(2, 1), "lag1_r"] - 0.6) < 0.05 and abs(st.loc[(2, 1), "delta_slope"] + 0.4) < 0.05
    assert abs(st.loc[(1, 1), "sd"] - 0.1) < 0.01


def test_sequential_bound_stats_min_trials():
    d = pd.DataFrame(
        {"subject_index": 1, "block_index": 1, "trial_number": range(5), "abs_bound": [0.1, 0.2, 0.3, 0.2, 0.1]}
    )
    st = get_sequential_bound_stats(d, min_trials=20)
    assert st.loc[(1, 1), "n_trials"] == 5 and np.isnan(st.loc[(1, 1), "delta_slope"])


def _post_error_sequence(rng, n, effect, carry=0.5):
    """Bounds with carryover; errors more likely after low bounds; optional post-error boost."""
    v, correct = np.empty(n), np.empty(n)
    v[0], correct[0] = 1.0, 1
    for i in range(1, n):
        v[i] = 1 + carry * (v[i - 1] - 1) + effect * (1 - correct[i - 1]) + rng.normal(0, 0.2)
        correct[i] = rng.random() < np.clip(0.8 + 0.5 * (v[i] - 1), 0.05, 0.95)
    return v, correct


def test_post_error_bound_effect_recovers_boost_despite_carryover():
    rng = np.random.default_rng(2)
    rows = []
    for s, effect in ((1, 0.0), (2, 0.2)):
        v, correct = _post_error_sequence(rng, 20000, effect)
        v[rng.random(len(v)) < 0.2] = np.nan  # unmeasured trials: previous value imputed
        rows.append(
            pd.DataFrame(
                {
                    "subject_index": s,
                    "block_index": 1,
                    "trial_number": np.arange(len(v)),
                    "abs_bound": v,
                    "correct": correct,
                }
            )
        )
    st = get_post_error_bound_effect(pd.concat(rows).sample(frac=1, random_state=0))
    med = {s: np.nanmedian(r.abs_bound) for s, r in zip((1, 2), rows)}
    assert abs(st.loc[(1, 1), "post_error_effect"]) < 0.02
    assert abs(st.loc[(2, 1), "post_error_effect"] * med[2] - 0.2) < 0.03
    assert st.loc[(1, 1), "n_prev_imputed"] > 0


def test_post_error_bound_effect_needs_previous_trial_and_errors():
    d = pd.DataFrame(
        {"subject_index": 1, "block_index": 1, "trial_number": [1, 2, 4, 5, 6] * 4, "abs_bound": 1.0, "correct": 1}
    )
    d["trial_number"] += np.repeat([0, 10, 20, 30], 5)
    st = get_post_error_bound_effect(d, min_post_error=1, min_trials=1)
    assert st.loc[(1, 1), "n_trials"] == 12 and st.loc[(1, 1), "n_post_error"] == 0
    assert np.isnan(st.loc[(1, 1), "post_error_effect"])


def test_apply_quality_filter_keeps_wall_hits_and_short_trials():
    # One subject, two blocks; every other trial is a wall hit with DT = 1, and only those trials carry the
    # between-block change. The standard filter drops them; apply_quality_filter=False keeps them.
    n = 40
    rows = []
    for block, shift in ((1, 0.0), (2, 0.3)):
        l_odd = np.arange(n) % 2 == 1
        rows.append(
            pd.DataFrame(
                {
                    "subject_index": 1,
                    "block_index": block,
                    "trial_number": np.arange(1, n + 1),
                    "abs_bound": np.where(l_odd, 0.3 + shift, 0.3) + np.linspace(0, 0.01, n),
                    "DT": np.where(l_odd, 1, 3),
                    "wall_hit": l_odd,
                }
            )
        )
    d = pd.concat(rows, ignore_index=True)
    p_std, _ = between_block_significance(d, [1, 2])
    p_all, sig_all = between_block_significance(d, [1, 2], apply_quality_filter=False)
    assert p_std[0, 1] > 0.05 and p_all[0, 1] < 0.05 and sig_all[0, 1]
    _, curves_std, _, _ = compute_per_subject_curves_with_nulls(d, 10, [1], n_perm=2)
    _, curves_all, _, _ = compute_per_subject_curves_with_nulls(d, 10, [1], n_perm=2, apply_quality_filter=False)
    # The z-scored curves differ because the kept trials differ.
    assert not np.allclose(curves_std, curves_all, equal_nan=True)
