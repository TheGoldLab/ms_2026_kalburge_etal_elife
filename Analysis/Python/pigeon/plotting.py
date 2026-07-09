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


def add_panel_label(ax, label, dx=-0.15, dy=1.08):
    """Add a bold, 14-pt Helvetica panel label (e.g. 'A') at the upper-left of an axes."""
    ax.text(dx, dy, label, transform=ax.transAxes,
            fontsize=14, fontweight='bold', fontfamily='Helvetica',
            ha='left', va='top')
