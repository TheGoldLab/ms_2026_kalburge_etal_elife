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
CONDITION_LABELS = {1: 'no penalty', 2: 'reward cost', 3: 'step cost'}

# Row labels for figures with one row per task variant (OL = blocked SNR,
# MX = mixed SNR), e.g. Figure05_mixedVsBlockedSNR, Figure05S01_boundDiffByDT.
TASK_ROW_LABELS = {'OL': 'Blocked SNR', 'MX': 'Mixed SNR'}


def add_panel_label(ax, label, dx=-0.15, dy=1.08):
    """Add a bold, 14-pt Helvetica panel label (e.g. 'A') at the upper-left of an axes."""
    ax.text(dx, dy, label, transform=ax.transAxes,
            fontsize=14, fontweight='bold', fontfamily='Helvetica',
            ha='left', va='top')
