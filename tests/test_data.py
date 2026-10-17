"""
Tests for pigeon.data: trial-level helpers on small hand-built tables with known answers.

Covers the steps before the decision (signed toward the choice), the bias-correction inversion
(``apply_bias_corrections``; no figure uses it, but it stays available), and the per-subject bound
summary.
"""

import numpy as np
import pandas as pd

from pigeon.data import get_steps_before_decision


def test_steps_before_decision_signed_toward_choice():
    """
    Steps before the decision step are taken in reverse order and signed toward the choice; missing steps and
    missing DT give NaN.
    """
    d = pd.DataFrame(
        {
            "steps": [
                np.array([0, 0.1, 0.3, 0.2, 0.6]),
                np.array([0, -0.2, -0.5]),
                np.array([0, 0.4]),
                np.array([0, 0.1, 0.2]),
            ],
            "choice": [1, 0, 1, 1],
            "DT": [4, 2, 1, np.nan],
        }
    )
    s = get_steps_before_decision(d, num_steps=3)
    np.testing.assert_allclose(s.loc[0], [0.4, -0.1, 0.2])  # steps[4]-steps[3], [3]-[2], [2]-[1]
    np.testing.assert_allclose(s.loc[1, ["step_0", "step_1"]], [0.3, 0.2])  # left choice: sign flipped
    assert np.isnan(s.loc[1, "step_2"])
    assert s.loc[2, "step_0"] == 0.4 and np.isnan(s.loc[2, "step_1"])
    assert s.loc[3].isna().all()


def test_bias_correction_inverts_the_calibration_curve(tmp_path):
    """
    A measured bound maps back to the true bound through the calibration curve of its DT and SNR bin, with linear
    extrapolation beyond the grid; trials without a DT are left uncorrected.
    """
    import scipy.io

    from pigeon.data import apply_bias_corrections

    # Calibration: measured = 1.5 x true in SNR bin 0 (|snr| < 0.5), measured = true in bin 1, 2 DT bins.
    sim_bounds = np.array([0.1, 0.2, 0.4])
    summary = np.stack([np.stack([1.5 * sim_bounds, sim_bounds], axis=1)] * 2, axis=1)  # (bounds, DT, SNR)
    path = tmp_path / "calib.mat"
    scipy.io.savemat(path, {"boundSummary": summary, "simBounds": sim_bounds, "snrBinEdges": np.array([0.5])})
    d = pd.DataFrame(
        {
            "bound": [0.3, -0.3, 0.9, 0.3, 0.3, 0.3],
            "DT": [1, 1, 2, 7, 1, np.nan],
            "snr": [0.2, -0.2, 0.2, 0.2, 0.8, 0.2],
        }
    )
    out = apply_bias_corrections(d, path)
    np.testing.assert_allclose(out["bound"][:5], [0.2, -0.2, 0.6, 0.2, 0.3])  # 0.9 -> 0.6: extrapolated
    assert out["bound"][5] == 0.3  # no DT: left uncorrected
    np.testing.assert_allclose(out["abs_bound"], np.abs(out["bound"]))


def test_bound_summary_by_block_snr_and_dt():
    """Mean, SD and count of |bound| per subject, block, |SNR| and DT, and pooled over SNR and DT."""
    from pigeon.data import get_bound_summary

    d = pd.DataFrame(
        {
            "subject_index": [1, 1, 1, 2],
            "block_index": [1, 1, 1, 1],
            "bound": [0.2, -0.4, 0.3, 0.5],
            "DT": [2, 2, 3, 2],
            "snr": [0.3, 0.3, -1.0, 0.3],
            "correct": [1, 0, 1, 1],
            "trial_number": [10, 11, 12, 10],
            "wall_hit": False,
            "rt_below_cutoff": False,
        }
    )
    s = get_bound_summary(d, max_rt=3)
    assert s.shape == (2, 1, 2, 3, 3)  # subjects, blocks, |snr| (0.3, 1.0), DT 1-3, stats
    np.testing.assert_allclose(s[0, 0, 0, 1], [0.3, np.std([0.2, 0.4], ddof=1), 2])
    np.testing.assert_allclose(s[0, 0, 1, 2], [0.3, np.nan, 1])
    pooled = get_bound_summary(d, split_by_snr=False, max_rt="all")
    np.testing.assert_allclose(pooled[0, 0, 0, 0, [0, 2]], [0.3, 3])
