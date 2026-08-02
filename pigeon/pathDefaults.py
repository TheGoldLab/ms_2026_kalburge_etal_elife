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
# Top-level directory containing one flat folder of per-subject CSVs per task
# type: MX/, MXSC/, OL/, PD/ (no Pigeon_ prefix, no prolificcsvs/ subfolder --
# see get_data_table's csv_pattern). MXSC (change-point task) lives alongside
# the other task types here -- get_data_table(task_type=...) picks the right
# subfolder regardless of task type.
#
# The raw data is frozen, so rather than keeping an unpacked copy inside the
# repo (and re-zipping/unzipping it on every use), a compressed archive
# (data/pigeon_raw_human.tar.gz) is checked in and unpacked once into this
# external directory -- see scripts/unpack_data.sh.
RAW_DATA_DIR = PROJECT_ROOT.parent / 'Data' / 'Raw' / 'Human'

if not RAW_DATA_DIR.exists():
    raise FileNotFoundError(
        f"Raw data directory not found: {RAW_DATA_DIR}\n"
        f"Run scripts/unpack_data.sh to unpack data/pigeon_raw_human.tar.gz there first."
    )

# ── Processed / derived data (stored with the project) ────────────────────────
DATA_DIR = PROJECT_ROOT / 'data' / 'processed'

BIAS_CORRECTION_FILE    = DATA_DIR / 'boundBiasCorrection.mat'     # bound-bias calibration (interpolation preferred; legacy linear-fit fallback)
BIAS_CORRECTION_CP_FILE = DATA_DIR / 'boundBiasCorrection_CP.mat'  # bound-bias calibration at the CP task's (much smaller) generative scale
RR_MATS_FILE             = DATA_DIR / 'RRMats.mat'                  # CP reward-rate matrices

# ── Figures output ─────────────────────────────────────────────────────────────
# Shared Figures/ folder one level above the project root (i.e. a sibling of
# Code/, at the 2025_Pigeon project level).
FIGURES_DIR = PROJECT_ROOT.parent / 'Figures'
