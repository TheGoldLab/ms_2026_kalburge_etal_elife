# Archived notebooks

Notebooks that no longer produce a paper figure or a pipeline input. They are kept for reference and
are not maintained: some import functions that have since been removed from `pigeon` (see git
history), and all were written to run from `notebooks/` (to run one from here, change
`sys.path.insert(0, '..')` to `'../..'` and `Path('../data/...')` to `Path('../../data/...')`).

| Notebook | What it was |
|---|---|
| `Figure03S01_congruenceByRT`, `Figure03S02_stepSizeBeforeBound`, `Figure03S03_boundTest`, `Figure03S04_sequentialAnalysis`, `Figure03S06_conditionalAccuracy` | Figure 3 supplements from before the stopping model (fixed-bound simulations as the comparison) |
| `Figure03S02_commitHazard` | Model-free commit hazard by position and step |
| `Figure03S05_sequentialAnalysisPD` | Sequential structure of the bounds set in the predefined-bound task |
| `Figure05S01_boundDiffByDT` | High − low SNR difference of measured bounds by DT |
| `Figure07_biasCorrection` | Bias-correction example figure |
| `Make_biasCorrection` | Bound bias-correction calibrations (`data/processed/archive/boundBiasCorrection*.mat`); used for the adaptation-transient exclusion until the stopping-model trials became trial ≥ 10 only |
| `Table_slopeAnalyses` | Slopes of measured bound vs. DT and of Δbound vs. bound, all blocks |
| `Make_RRMatrix`, `Test_cpData` | Change-point analyses based on reward-rate gradients over pre-/post-change bound grids |
| `Test_stoppingModel` | Development of the stopping model: recovery, variants, posterior checks |
