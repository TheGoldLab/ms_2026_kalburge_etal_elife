"""Tests for pigeon.adaptation."""

import numpy as np
import pandas as pd

from pigeon.adaptation import get_sequential_bound_stats


def test_sequential_bound_stats_independent_vs_autocorrelated():
    rng = np.random.default_rng(0)
    n = 4000
    iid = rng.normal(0.4, 0.1, n)
    ar = np.empty(n)
    ar[0] = 0.4
    for i in range(1, n):                       # AR(1) with coefficient 0.6 around 0.4
        ar[i] = 0.4 + 0.6 * (ar[i - 1] - 0.4) + rng.normal(0, 0.08)
    # Rows shuffled: the statistics must order trials by trial_number, not by row.
    d = pd.concat([pd.DataFrame({"subject_index": s, "block_index": 1, "trial_number": np.arange(n),
                                 "abs_bound": v}) for s, v in ((1, iid), (2, ar))]).sample(frac=1, random_state=1)
    st = get_sequential_bound_stats(d)
    assert abs(st.loc[(1, 1), "delta_slope"] + 1) < 0.05 and abs(st.loc[(1, 1), "lag1_r"]) < 0.05
    assert abs(st.loc[(2, 1), "lag1_r"] - 0.6) < 0.05 and abs(st.loc[(2, 1), "delta_slope"] + 0.4) < 0.05
    assert abs(st.loc[(1, 1), "sd"] - 0.1) < 0.01


def test_sequential_bound_stats_min_trials():
    d = pd.DataFrame({"subject_index": 1, "block_index": 1, "trial_number": range(5), "abs_bound": [.1, .2, .3, .2, .1]})
    st = get_sequential_bound_stats(d, min_trials=20)
    assert st.loc[(1, 1), "n_trials"] == 5 and np.isnan(st.loc[(1, 1), "delta_slope"])
