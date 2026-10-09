"""Tests for the CP calibration consistency checks in pigeon.data."""

import numpy as np
import pandas as pd
import pytest
import scipy.io

from pigeon.data import (
    check_calibration_snrs,
    get_cp_generative_params,
    get_cp_reward_params,
    load_cp_rr_mats,
)


def _cp_table(high_mean=0.03, std=0.05, lh_steps=(5, 9), hl_steps=(4, 7)):
    """Minimal MXSC-style table: fixed low/high blocks 1/2, CP blocks 3/4."""
    low_mean = 0.01
    rows = []
    for block, mean, cps in (
        (1, low_mean, [0]),
        (2, high_mean, [0]),
        (3, low_mean, list(lh_steps)),
        (4, high_mean, list(hl_steps)),
    ):
        for sign in (1, -1):
            for cp in cps:
                rows.append(
                    {
                        "block_index": block,
                        "snr": sign * mean / std,
                        "step_std": std,
                        "change_point": cp,
                    }
                )
    return pd.DataFrame(rows)


def _save_rr(
    path,
    g_means=(0.01, 0.03),
    g_std=0.05,
    lh=(5, 9),
    hl=(4, 7),
    coins_lost=1.0,
    reward=True,
):
    pmats = np.empty((1, 2), dtype=object)
    pmats[0, 0] = np.zeros((2, 2, len(lh)))
    pmats[0, 1] = np.zeros((2, 2, len(hl)))
    scipy.io.savemat(
        path,
        {
            "pmats": pmats,
            "bounds": np.array([0.1, 0.2]),
            "cp_steps_lh": np.array(lh),
            "cp_steps_hl": np.array(hl),
            "g_means": np.array(g_means),
            "g_std": g_std,
            **(
                {
                    "coins_gained": 1.0,
                    "coins_lost": coins_lost,
                    "steps_per_block": 1000.0,
                }
                if reward
                else {}
            ),
        },
    )


def _raw_dir(tmp_path, coins_lost=(1, 1)):
    """Fake raw-data dir: two MXSC files whose block metadata rows log the reward settings."""
    (tmp_path / "MXSC").mkdir()
    for i, lost in enumerate(coins_lost):
        pd.DataFrame(
            {
                "tc_coins_gained_per_correct": [1, np.nan, 1],
                "tc_coins_lost_per_error": [lost, np.nan, lost],
                "tc_steps_max": [1000, np.nan, 1000],
                "tc_steps_taken_to_start_trial": [1, np.nan, 1],
                "tc_steps_lost_per_error": [0, np.nan, 0],
                "trial_number": [np.nan, 1, np.nan],
            }
        ).to_csv(tmp_path / "MXSC" / f"s{i}.csv", index=False)
    return tmp_path


def test_get_cp_generative_params_reads_fixed_blocks():
    params = get_cp_generative_params(_cp_table())
    assert params["low"] == pytest.approx((0.01, 0.05))
    assert params["high"] == pytest.approx((0.03, 0.05))


def test_get_cp_generative_params_rejects_mixed_designs():
    mixed = pd.concat([_cp_table(high_mean=0.02), _cp_table(high_mean=0.03)])
    with pytest.raises(ValueError, match="Block 2"):
        get_cp_generative_params(mixed)


def test_check_calibration_snrs_passes_when_covered():
    check_calibration_snrs([0.2, 0.6], _cp_table())


def test_check_calibration_snrs_flags_uncovered_snr():
    # The 2025 calibration (SNR 0.2/0.4) applied to 2026 data (0.2/0.6).
    with pytest.raises(ValueError, match="0.6"):
        check_calibration_snrs([0.2, 0.4], _cp_table())


def test_load_cp_rr_mats_accepts_matching_file(tmp_path):
    path = tmp_path / "rr.mat"
    _save_rr(path)
    rr = load_cp_rr_mats(path, _cp_table(), data_dir=_raw_dir(tmp_path))
    assert np.allclose(rr["g_means"], [0.01, 0.03])


def test_load_cp_rr_mats_rejects_wrong_snr(tmp_path):
    path = tmp_path / "rr.mat"
    _save_rr(path, g_means=(0.01, 0.02))
    with pytest.raises(ValueError, match="g_means"):
        load_cp_rr_mats(path, _cp_table(), data_dir=_raw_dir(tmp_path))


def test_load_cp_rr_mats_rejects_missing_cp_step(tmp_path):
    path = tmp_path / "rr.mat"
    _save_rr(path, lh=(5,))
    with pytest.raises(ValueError, match="cp_steps_lh"):
        load_cp_rr_mats(path, _cp_table(), data_dir=_raw_dir(tmp_path))


def test_get_cp_reward_params_reads_logged_settings(tmp_path):
    params = get_cp_reward_params(_raw_dir(tmp_path))
    assert params == {
        "coins_gained": 1,
        "coins_lost": 1,
        "steps_per_block": 1000,
        "steps_to_start": 1,
        "steps_lost": 0,
    }


def test_get_cp_reward_params_rejects_inconsistent_files(tmp_path):
    with pytest.raises(ValueError, match="tc_coins_lost_per_error"):
        get_cp_reward_params(_raw_dir(tmp_path, coins_lost=(1, 4)))


def test_load_cp_rr_mats_rejects_wrong_reward(tmp_path):
    # The inherited simulation default (lose 4 coins) vs. the task's logged 1.
    path = tmp_path / "rr.mat"
    _save_rr(path, coins_lost=4.0)
    with pytest.raises(ValueError, match="coins_lost"):
        load_cp_rr_mats(path, _cp_table(), data_dir=_raw_dir(tmp_path))


def test_load_cp_rr_mats_rejects_unrecorded_reward(tmp_path):
    path = tmp_path / "rr.mat"
    _save_rr(path, reward=False)
    with pytest.raises(ValueError, match="does not record"):
        load_cp_rr_mats(path, _cp_table(), data_dir=_raw_dir(tmp_path))
