"""Path defaults for the Pigeon Code project.

All project-wide file and directory paths are defined here.  Edit this file
to re-point the project at a new data location without touching any notebook
or analysis routine.
"""

from pathlib import Path

# ── Directory anchors ──────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent   # pigeon/
PROJECT_ROOT = _HERE.parent               # Code/

# ── Raw CSV data (frozen dataset, lives outside the repo) ──────────────────────
# One flat folder of per-subject CSVs per task: MX/, MXSC/, OL/, PD/. Unpacked
# once from the archive data/pigeon_raw_human.tar.gz by scripts/unpack_data.sh.
RAW_DATA_DIR = PROJECT_ROOT.parent / 'Data' / 'Raw' / 'Human'

if not RAW_DATA_DIR.exists():
    raise FileNotFoundError(
        f"Raw data directory not found: {RAW_DATA_DIR}\n"
        f"Run scripts/unpack_data.sh to unpack data/pigeon_raw_human.tar.gz there first."
    )

# ── Processed / derived data (stored with the project) ────────────────────────
DATA_DIR = PROJECT_ROOT / 'data' / 'processed'

# Bound-bias calibrations (notebooks/Make_biasCorrection.ipynb): cohorts 1 and 2, and the change-point task
BIAS_CORRECTION_FILE    = DATA_DIR / 'boundBiasCorrection.mat'
BIAS_CORRECTION_CP_FILE = DATA_DIR / 'boundBiasCorrection_CP.mat'

# ── Figures output ─────────────────────────────────────────────────────────────
# Shared Figures/ folder one level above the project root (i.e. a sibling of
# Code/, at the 2025_Pigeon project level).
FIGURES_DIR = PROJECT_ROOT.parent / 'Figures'
