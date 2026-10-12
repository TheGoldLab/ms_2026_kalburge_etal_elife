"""Tests for pigeon.data."""

import numpy as np
import pandas as pd

from pigeon.data import get_steps_before_decision


def test_steps_before_decision_signed_toward_choice():
    d = pd.DataFrame({"steps": [np.array([0, .1, .3, .2, .6]), np.array([0, -.2, -.5]), np.array([0, .4]),
                                np.array([0, .1, .2])],
                      "choice": [1, 0, 1, 1], "DT": [4, 2, 1, np.nan]})
    s = get_steps_before_decision(d, num_steps=3)
    np.testing.assert_allclose(s.loc[0], [.4, -.1, .2])          # steps[4]-steps[3], [3]-[2], [2]-[1]
    np.testing.assert_allclose(s.loc[1, ["step_0", "step_1"]], [.3, .2])   # left choice: sign flipped
    assert np.isnan(s.loc[1, "step_2"])
    assert s.loc[2, "step_0"] == 0.4 and np.isnan(s.loc[2, "step_1"])
    assert s.loc[3].isna().all()
