"""Tests for the CP calibration consistency checks in pigeon.data."""

import pandas as pd
import pytest

from pigeon.data import check_calibration_snrs, get_cp_generative_params


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
