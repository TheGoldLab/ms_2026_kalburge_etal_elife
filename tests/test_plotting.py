"""Tests for pigeon.plotting text helpers."""

from pigeon.plotting import format_p, format_rho


def test_format_p_uses_floor_and_three_decimals():
    assert format_p(0.0123) == "p=0.012"
    assert format_p(0.0004) == "p<0.001"
    assert format_p(0.001) == "p=0.001"


def test_format_rho_uses_true_minus():
    assert format_rho(-0.221) == "ρ=−0.22"
    assert format_rho(0.468, digits=3) == "ρ=0.468"
