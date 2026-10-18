"""Tests for pigeon.plotting: the text helpers that format p values and correlations, and off-scale subject points."""

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pigeon.plotting import format_p, format_rho, plot_subject_points


def test_format_p_uses_floor_and_three_decimals():
    """p values print with three decimals and as p<0.001 below that."""
    assert format_p(0.0123) == "p=0.012"
    assert format_p(0.0004) == "p<0.001"
    assert format_p(0.001) == "p=0.001"


def test_format_rho_uses_true_minus():
    """Correlations print with a true minus sign and the requested digits."""
    assert format_rho(-0.221) == "ρ=−0.22"
    assert format_rho(0.468, digits=3) == "ρ=0.468"


def test_plot_subject_points_marks_off_scale_points():
    """Points beyond the limits are clamped to the edge as triangles pointing off-scale; NaN points are skipped."""
    fig, ax = plt.subplots()
    x = [0.5, 2.0, -1.0, 0.5, 0.5, np.nan]
    y = [0.5, 0.5, 0.5, 3.0, -2.0, 0.5]
    l_edge = plot_subject_points(ax, x, y, xlim=(0, 1), ylim=(0, 1))
    assert l_edge.tolist() == [False, True, True, True, True, False]
    drawn = {line.get_marker(): (line.get_xdata().tolist(), line.get_ydata().tolist()) for line in ax.lines}
    assert drawn == {
        "o": ([0.5], [0.5]),
        ">": ([1.0], [0.5]),
        "<": ([0.0], [0.5]),
        "^": ([0.5], [1.0]),
        "v": ([0.5], [0.0]),
    }
    plt.close(fig)
