"""Shared style for the figure notebooks.

Every paper figure uses the same fonts and color roles: ``use_figure_style()``
sets 12-pt axis and tick labels (``FS``) in Helvetica, with fonts embedded so
figure text stays editable in Illustrator; in-panel text (legends, statistics)
is ``FS_INSET`` = 8 pt; figure sizes are given in cm (``CM`` converts to
inches); panel letters come from ``add_panel_label``. Data are black, the
fitted stopping model blue and optimal benchmarks red (``DATA_COLOR``,
``MODEL_COLOR``, ``OPTIMAL_COLOR``).
"""

import matplotlib.pyplot as plt

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
    Add a bold, 14-pt Helvetica panel label (e.g. 'A') at the upper-left of an axes.

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
        fontfamily="Helvetica",
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
