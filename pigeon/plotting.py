"""Shared style for the figure notebooks.

Every paper figure uses the same fonts and color roles: ``use_figure_style()``
sets 12-pt axis and tick labels (``FS``) in Helvetica, with fonts embedded so
figure text stays editable in Illustrator; in-panel text (legends, statistics)
is ``FS_INSET`` = 8 pt; figure sizes are given in cm (``CM`` converts to
inches); panel letters come from ``add_panel_label``. Data are black, the
fitted stopping model blue and optimal benchmarks red (``DATA_COLOR``,
``MODEL_COLOR``, ``OPTIMAL_COLOR``). Per-subject points, single trials and excluded
fits use ``SUBJECT_MARKER``, ``TRIAL_MARKER`` and ``EXCLUDED_MARKER``.
"""

import matplotlib.pyplot as plt
import numpy as np

CM = 1 / 2.54  # inches per cm, for figure sizes given in cm
FS = 12  # axis and tick labels (pt)
FS_INSET = 8  # in-panel text: legends, statistics, colorbar labels (pt)

FONT_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
}

# Task-block condition names for cohort 1 (OL). Blocks 4-6 are the same three
# conditions repeated at high SNR (see data.py's blocks 4-6 -> 1-3 relabeling),
# so CONDITION_LABELS[block % 3 or 3] applies to those too.
CONDITION_LABELS = {1: "No penalty", 2: "Coin penalty", 3: "Step penalty"}

# Figure color roles: data (raw values, per-subject summaries and data medians) are black, with dense
# per-subject lines or points in light gray; the fitted stopping model is blue; optimal / normative
# benchmarks (ideal observer, reward-rate curves and their peaks, near-optimal contours) are red.
DATA_COLOR = "k"
MODEL_COLOR = "tab:blue"
OPTIMAL_COLOR = "tab:red"

# Marker styles, as keyword arguments for ``ax.plot`` (``ax.scatter`` takes ``SUBJECT_SCATTER``).
# Per-subject points are white with a black edge; single trials (many overlapping points, Figs 3B
# and 3S4) are smaller open circles; fits excluded at a fit limit are gray crosses. Points beyond
# the axis are drawn at the edge as triangles pointing off-scale: ``{**SUBJECT_MARKER, "marker": ">"}``
# (or '<', '^', 'v').
MARKER_SIZE = 5  # per-subject points (pt)
SUBJECT_MARKER = {"marker": "o", "ms": MARKER_SIZE, "mfc": "w", "mec": DATA_COLOR, "mew": 0.8, "ls": "none"}
SUBJECT_SCATTER = {"s": MARKER_SIZE**2, "facecolor": "w", "edgecolor": DATA_COLOR, "linewidths": 0.8}
TRIAL_MARKER = {"marker": "o", "ms": 3, "mfc": "none", "mec": DATA_COLOR, "mew": 0.5, "ls": "none"}
EXCLUDED_MARKER = {"marker": "x", "ms": MARKER_SIZE, "color": "0.55", "mew": 1.0, "ls": "none"}
# The participants' median (Figs 4-6): a large black circle with a white edge, over the subject points.
MEDIAN_MARKER = {"marker": "o", "ms": 12, "color": DATA_COLOR, "mec": "w", "mew": 2, "ls": "none"}

# Commit sources in the model (Figs 3F and 3S3C): guesses orange, lapses (random choices) dark gray.
# In Fig 3F lapses are white hatching over each source's bar (the lapse share of that source); in
# Fig 3S3C, where lapse is a category of its own, they are solid ``LAPSE_BAR['color']``.
GUESS_COLOR = "tab:orange"
LAPSE_BAR = {"color": "0.3", "edgecolor": "w", "hatch": "////"}

# Row labels for figures with one row per task variant (OL = blocked SNR,
# MX = mixed SNR), e.g. Figure05_mixedVsBlockedSNR.
TASK_ROW_LABELS = {"OL": "Blocked SNR", "MX": "Mixed SNR"}


def use_figure_style():
    """
    Set matplotlib's fonts for paper figures: ``FS``-pt labels, titles and ticks, ``FONT_RC``.

    Call before creating any axes: axes take their tick-label size when they are created.
    """
    plt.rcParams.update(
        {
            "font.size": FS,
            "axes.labelsize": FS,
            "axes.titlesize": FS,
            "xtick.labelsize": FS,
            "ytick.labelsize": FS,
            **FONT_RC,
        }
    )


def plot_subject_points(ax, x, y, xlim=None, ylim=None, **kwargs):
    """
    Per-subject points (``SUBJECT_MARKER``), with points beyond the axis limits drawn at the edge as
    triangles pointing off-scale.

    A point beyond the x limits gets '>' or '<'; one beyond only the y limits gets '^' or 'v'. NaN
    points are skipped.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
    x, y : array_like
        One value per subject.
    xlim, ylim : (float, float) or None
        Limits to clamp to; None leaves that axis unclamped.
    **kwargs
        Passed to ``ax.plot`` (e.g. ``zorder``), overriding ``SUBJECT_MARKER``.

    Returns
    -------
    numpy.ndarray of bool
        True for the points drawn at an edge (for the caption counts).
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    xlim = (-np.inf, np.inf) if xlim is None else xlim
    ylim = (-np.inf, np.inf) if ylim is None else ylim
    ok = np.isfinite(x) & np.isfinite(y)
    l_right, l_left = ok & (x > xlim[1]), ok & (x < xlim[0])
    l_x_in = ok & ~l_right & ~l_left
    l_up, l_down = l_x_in & (y > ylim[1]), l_x_in & (y < ylim[0])
    l_in = l_x_in & ~l_up & ~l_down
    xc, yc = np.clip(x, *xlim), np.clip(y, *ylim)
    for l_pts, marker in ((l_in, "o"), (l_right, ">"), (l_left, "<"), (l_up, "^"), (l_down, "v")):
        if l_pts.any():
            ax.plot(xc[l_pts], yc[l_pts], **{**SUBJECT_MARKER, "marker": marker, "clip_on": False, **kwargs})
    return ok & ~l_in


def add_row_xlabel(fig, axes, label, pad=0.005):
    """
    One x label centered under a row of panels that share it, just below their tick labels.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
    axes : sequence of matplotlib.axes.Axes
        The row, left to right.
    label : str
    pad : float
        Gap below the lowest tick label, in figure-height fractions.
    """
    fig.canvas.draw()
    left, right = axes[0].get_position().x0, axes[-1].get_position().x1
    bottom = min(ax.get_tightbbox().transformed(fig.transFigure.inverted()).y0 for ax in axes)
    fig.text((left + right) / 2, bottom - pad, label, ha="center", va="top", fontsize=FS)


def add_panel_label(ax, label, dx=-0.15, dy=1.08):
    """
    Add a bold, 14-pt panel label (e.g. 'A') at the upper-left of an axes.

    The label is set in Arial Bold: matplotlib reads only the regular face of macOS's Helvetica.ttc,
    so a bold Helvetica request silently renders regular.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Axes to label.
    label : str
        Label text, e.g. 'A'.
    dx, dy : float
        Position in axes-fraction coordinates (`ax.transAxes`: (0, 0) = lower-left,
        (1, 1) = upper-right of the axes). Defaults place the label just outside
        the upper-left corner; negative dx / dy > 1 are expected. See
        Figure03_boundSummary.ipynb for an example of rescaling dx for a
        narrower-than-usual panel.
    """
    ax.text(
        dx,
        dy,
        label,
        transform=ax.transAxes,
        fontsize=14,
        fontweight="bold",
        fontfamily="Arial",
        ha="left",
        va="top",
    )


def format_p(p):
    """
    Figure-text p value in the paper's compact style: 'p=0.012', or 'p<0.001' below 0.001.

    Parameters
    ----------
    p : float

    Returns
    -------
    str
    """
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def format_rho(rho, digits=2):
    """
    Figure-text Spearman correlation, 'ρ=0.47' or 'ρ=−0.22', with a true minus sign (U+2212).

    Parameters
    ----------
    rho : float
    digits : int
        Decimal places.

    Returns
    -------
    str
    """
    return f"ρ={rho:.{digits}f}".replace("-", "−")
