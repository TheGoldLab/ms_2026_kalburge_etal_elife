"""
Tests for the change-point (MXSC) design checks in pigeon.data.

``get_cp_generative_params`` reads the low/high step means from the fixed blocks, and
``check_calibration_snrs`` refuses a calibration simulated at SNRs the data don't use (e.g. the
2025 calibration applied to the 2026 cohort). The tests use a minimal hand-built MXSC-style table.
"""

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
    """The low and high step mean and SD are read from fixed blocks 1 and 2."""
    params = get_cp_generative_params(_cp_table())
    assert params["low"] == pytest.approx((0.01, 0.05))
    assert params["high"] == pytest.approx((0.03, 0.05))


def test_get_cp_generative_params_rejects_mixed_designs():
    """Data mixing two designs (different high-SNR step means) raise instead of being averaged."""
    mixed = pd.concat([_cp_table(high_mean=0.02), _cp_table(high_mean=0.03)])
    with pytest.raises(ValueError, match="Block 2"):
        get_cp_generative_params(mixed)


def test_check_calibration_snrs_passes_when_covered():
    """A calibration simulated at the data's SNRs passes."""
    check_calibration_snrs([0.2, 0.6], _cp_table())


def test_check_calibration_snrs_flags_uncovered_snr():
    """A calibration missing one of the data's SNRs raises, naming the missing SNR."""
    # The 2025 calibration (SNR 0.2/0.4) applied to 2026 data (0.2/0.6).
    with pytest.raises(ValueError, match="0.6"):
        check_calibration_snrs([0.2, 0.4], _cp_table())
