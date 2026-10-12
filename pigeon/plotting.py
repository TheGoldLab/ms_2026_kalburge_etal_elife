"""Shared style helpers for the figure/table notebooks.

FONT_RC embeds real (non-Type-3) font outlines in saved PDFs/EPS and sets
Helvetica as the typeface, so figure text survives as editable text objects
rather than per-character vector paths when opened in Illustrator etc.
"""

FONT_RC = {
    'font.family': 'sans-serif',
    'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
}

# Task-block condition names for cohort 1 (OL). Blocks 4-6 are the same three
# conditions repeated at high SNR (see data.py's blocks 4-6 -> 1-3 relabeling),
# so CONDITION_LABELS[block % 3 or 3] applies to those too.
CONDITION_LABELS = {1: 'No penalty', 2: 'Coin penalty', 3: 'Step penalty'}

# Row labels for figures with one row per task variant (OL = blocked SNR,
# MX = mixed SNR), e.g. Figure05_mixedVsBlockedSNR, Figure05S01_boundDiffByDT.
TASK_ROW_LABELS = {'OL': 'Blocked SNR', 'MX': 'Mixed SNR'}


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
    ax.text(dx, dy, label, transform=ax.transAxes,
            fontsize=14, fontweight='bold', fontfamily='Helvetica',
            ha='left', va='top')


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
    return 'p<0.001' if p < 0.001 else f'p={p:.3f}'


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
    return f'ρ={rho:.{digits}f}'.replace('-', '−')
