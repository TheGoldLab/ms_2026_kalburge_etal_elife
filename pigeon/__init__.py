"""
Pigeon — Python analysis package for the Pigeon task.

Modules
-------
data
    Load trial data from the raw CSV files; the direct (per-trial) bound
    measure, its NDT and DT, the standard trial filter, the bias correction,
    and per-subject summaries.

stopping
    The trial-level stopping model (time-varying bound with trial-to-trial
    variability, sensory noise, guesses, anticipations and lapses; NDT
    marginalized): likelihood, fitting, simulation, and the paper's
    stopping-model trial selection. The basis of Figures 3-6.

adaptation
    Within-block adaptation time constants (tau; Figure 4) and the
    trial-to-trial structure of the bound (Figure 3 Supplement 4).

simulation
    Fixed-bound simulations of the task (reward-rate benchmarks, bias
    calibration).

ideal_observer
    Reward-rate-optimal bounds by dynamic programming, including a reward that
    switches at a fixed step of every trial (design of the RC task; used by
    Design_rcTask). Imported directly (`from pigeon.ideal_observer import ...`).

plotting
    Shared figure style (fonts, sizes, colors, panel letters, p and rho
    formatting). Imported directly (`from pigeon.plotting import ...`).

pathDefaults
    All project-wide file and directory paths.

Public API
----------
get_data_table           Load real participant data as a DataFrame.
get_bounds               Infer per-trial bound and DT from step sequences.
get_good_trial_array     Boolean mask for the standard trial filter.
get_bound_summary        Mean |bound| per subject/block/SNR/DT bin.
get_performance_summary  Accuracy and DT stats per subject/block/SNR.
simulate_trials          Fixed-bound simulation engine (returns raw arrays).
get_simulated_data_table Simulated blocks in get_data_table format.
get_adaptation_tau_fits  Per-subject/block adaptation tau fits.
fit_stopping_model       Maximum-likelihood fit of the stopping model to one subject.
fit_stopping_models      The same for every subject in a data table.
simulate_stopping_trials Simulate trials from the stopping model.
stopping_model_nll       Negative log-likelihood under given stopping-model parameters.
get_stopping_model_trials Trials for stopping-model fits (the paper's trial selection).
"""

from .adaptation import get_adaptation_tau_fits
from .data import get_bound_summary, get_bounds, get_data_table, get_good_trial_array, get_performance_summary
from .simulation import get_simulated_data_table, simulate_trials
from .stopping import (
    fit_stopping_model,
    fit_stopping_models,
    get_stopping_model_trials,
    simulate_stopping_trials,
    stopping_model_nll,
)

__all__ = [
    "fit_stopping_model",
    "fit_stopping_models",
    "get_adaptation_tau_fits",
    "get_bound_summary",
    "get_bounds",
    "get_data_table",
    "get_good_trial_array",
    "get_performance_summary",
    "get_simulated_data_table",
    "get_stopping_model_trials",
    "simulate_stopping_trials",
    "simulate_trials",
    "stopping_model_nll",
]
