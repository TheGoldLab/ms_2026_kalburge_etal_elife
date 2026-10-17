# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


**Naming**
- Functions: snake_case, verb-first (`get_data_table`, `apply_bias_corrections`, `fit_exp_tau`). Module-private helpers get a leading underscore (`_compute_rt_cutoff`, `_build_window_matrix`).
- Constants: UPPER_SNAKE_CASE (`WALL`, `MIN_BOUND`, `BLOCK_DEFAULTS`, the path constants in `pathDefaults.py`).
- Boolean mask variables carry a MATLAB-inherited `l`-prefix instead of `is_`/`has_` names: `lg` (good-trial mask), and short combinable masks like `ls`, `lsb`, `lsnr`, `lrt`, `lc` that get ANDed together (`lg & ls & lsnr`) as filters narrow. Follow this pattern rather than introducing `is_valid`/`mask_x` names when editing `data.py` or `adaptation.py`.
- Loop indices pair an abbreviation with its source collection: `si`/`subj` (subject), `bi`/`block`, `ni` or `mm` (SNR), `ri` (RT/DT bin), `dd` (DT bin), `ii`/`tt` (trial).
- Domain abbreviations (`DT`, `RT`, `NDT`, `SNR`, `DV`) stay uppercase in DataFrame column names (`data_table["DT"]`, `data_table["RT"]`) but lowercase in local variables/params (`dts`, `rts`, `ndts`, `min_dt`) — match whichever context you're in, don't normalize one to the other.
- `abs_` prefix marks the absolute-value variant of an existing name (`bound` → `abs_bound`, `snr` → `abs_snr`, `DV` → `abs_DV`) rather than a differently-named variable.
- Distribution/range parameters use `_mean`/`_std` and `_min`/`_max` suffixes (`generative_mean`, `bound_std`, `ndt_min`), even for one-off simulation knobs.
- `data_table` is the conventional first-positional-arg name for any function consuming the standard trial-level schema (`data.py`, `adaptation.py`) — keep using it rather than `df`.

**Randomness**
- Stochastic functions (`simulate_trials`, `get_simulated_data_table`, `compute_per_subject_curves_with_nulls`) take `rng=None` and default internally to `np.random.default_rng()` (or a fixed `seed` for permutation tests). Thread a caller-supplied `Generator` through rather than calling `np.random` module-level functions, so callers can control reproducibility.

**Docstrings**
- NumPy-style (`Parameters`/`Returns` sections with dashed underlines) on every public function.
- When a function is a direct port of MATLAB code, note the source file in the first lines (`Translated from getPigeon_bounds.m`) — keep doing this for anything still being ported. The MATLAB originals are archived outside the repository, in `../Archive/matlab`.
- Module docstrings describe the pipeline/algorithm in enough detail to avoid reading the whole file (see the tops of `data.py`, `simulation.py`), not just a one-line summary.

**Comments**
- Inline comments justify *why*, especially non-obvious math or a MATLAB-compatibility constraint (e.g. `simulation.py`'s NDT draw citing the exact MATLAB `randi` expression it reproduces). Don't add comments that restate the code.

**Notebooks**
- Filename pattern: `<Category><NN>[S<NN>]_<camelCaseDescription>.ipynb`. Categories: `Figure` (main figure), `FigureNNSNN_` (supplement, numbered under its parent figure), `Explore_` (analyses behind a methods choice, and data exploration), `Design_` (task design), `Make_` / `Table_` (preprocessing / tables, none current). Number figures to match the paper. Superseded notebooks go to `notebooks/archive/`.
- New analysis notebooks should call into `pigeon` rather than reimplementing bound inference, trial filtering, or summary stats inline — that duplication is exactly what the package exists to prevent.

**Vectorization**
- Prefer vectorized NumPy over per-trial Python loops for anything running at simulation scale (see `simulate_trials`'s crossing detection, explicitly commented "fully vectorized, no Python step loop"). The per-trial loops in `get_bounds` (`data.py`) are a deliberate exception kept for clarity/parity with the MATLAB original — don't assume they need vectorizing too.

**Miscellaneous**
- Always use American, not British, English