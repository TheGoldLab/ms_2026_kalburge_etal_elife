"""
Pigeon — Python analysis package for the Pigeon task.

Modules
-------
data
    Load and pre-process trial data from raw CSV files.  Computes per-trial
    bounds, decision times (DT), response times (RT), and applies optional
    bias correction.  Also contains summary statistics over the processed
    data table — per-subject/block/SNR accuracy, DT distributions, bound
    statistics binned by DT, and the change-point-specific composed summary
    (`get_bound_summaries_wcp`).

simulation
    Generative model of the task.  Simulates a random-walk accumulator with
    an absorbing bound, NDT, and optional lapse rate.  Can reproduce a full
    data-table in the same format as `get_data_table`.

stopping
    Trial-level stopping model (variable bound + guesses + anticipations +
    choice lapses, NDT marginalized) fit to each trial's full path; used by
    Test_stoppingModel to estimate guessing and test change-point shifts.

adaptation
    Within-block adaptation time-constant (tau) fits, shared by
    Figure04_RRvsBound (source of the tau insets in panels D-F) and any
    notebook that gates trials on a subject's own adaptation time constant.

ideal_observer
    Reward-rate-optimal bounds by dynamic programming, including a reward that
    switches at a fixed step of every trial (design of the RC task; used by
    Test_cpRDesign). Imported directly (`from pigeon.ideal_observer import ...`).

plotting
    Shared style helpers for the figure/table notebooks (FONT_RC,
    add_panel_label, and condition/task label dicts). Imported directly
    (`from pigeon.plotting import ...`), not re-exported below.

Public API
----------
get_data_table          Load real participant data as a DataFrame.
get_bounds              Infer per-trial bound and DT from step sequences.
get_good_trial_array    Boolean mask for standard trial-quality filters.
get_bound_summary       Mean |bound| per subject/block/SNR/DT bin.
get_performance_summary Accuracy and DT stats per subject/block/SNR.
get_bound_summaries_wcp Change-point-specific composed bound summary (Figure06/Make_RRMatrix pipeline).
get_cp_generative_params CP task's low/high-SNR step mean and SD, read from the data.
get_cp_reward_params    CP task's reward structure, read from the raw files' logged settings.
load_cp_rr_mats         Load RRMats.mat, verifying it matches the data's CP design.
simulate_trials         Core simulation engine (returns raw arrays).
get_simulated_data_table Full simulated data table matching get_data_table format.
get_adaptation_tau_fits Per-subject/block adaptation tau fits (Figure04 pipeline).
fit_stopping_model      Maximum-likelihood fit of the stopping model to one subject.
simulate_stopping_trials Simulate trials from the stopping model.
stopping_model_nll      Negative log-likelihood under given stopping-model parameters.
"""

from .data import (
    get_data_table, get_bounds, get_good_trial_array,
    get_bound_summary, get_performance_summary, get_bound_summaries_wcp,
    get_cp_generative_params, get_cp_reward_params, load_cp_rr_mats,
)
from .simulation import simulate_trials, get_simulated_data_table
from .adaptation import get_adaptation_tau_fits
from .stopping import fit_stopping_model, simulate_stopping_trials, stopping_model_nll
