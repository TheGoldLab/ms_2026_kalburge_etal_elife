"""Null check for the tc_by_snr variant: does one time course per SNR look different when it isn't?

Simulates each subject's real trials once from their main fit (one time-course
shape shared across SNRs), then fits both the main model and tc_by_snr to the
simulated data. Low- vs. high-SNR shape differences and the AIC gain found
here come from estimation alone (e.g. high-SNR trials rarely reach late steps,
so the penalty pulls the late slope toward 0); notebooks/Test_stoppingModel.ipynb
compares them with the real-data fits.

Writes data/processed/stopping_fits_null_snr_<main|tc_by_snr>.pkl. Run from
the project root:

    PYTHONPATH=. nohup uv run python scripts/run_stopping_tc_snr_null.py > data/processed/stopping_fits_null_snr.log 2>&1 &
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd

from pigeon.stopping import fit_stopping_models, get_stopping_model_trials, simulate_stopping_data_table

OUT_DIR = Path("data/processed")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}
SEED = 20261011


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main():
    rng = np.random.default_rng(SEED)
    main_fits = pd.read_pickle(OUT_DIR / "stopping_fits_main.pkl")
    out = {"main": [], "tc_by_snr": []}
    for task, blocks in DATASETS.items():
        d = get_stopping_model_trials(task, blocks)
        sim = simulate_stopping_data_table(d, main_fits[main_fits.task == task], group_col="condition",
                                           num_reps=1, rng=rng)
        lo = np.isclose(sim["snr"].abs(), sim["snr"].abs().min())
        sim["snr_level"] = np.where(lo, "lo", "hi")
        log(f"{task}: simulated {len(sim):,} trials ({len(d):,} real)")
        for variant, kwargs in (("main", {}), ("tc_by_snr", {"time_course_col": "snr_level"})):
            t0 = time.time()
            f = fit_stopping_models(sim, group_col="condition", **kwargs).assign(task=task)
            n_bad = int((~f.groupby("subject_index").success.first()).sum())
            log(f"{variant} {task}: {f.subject_index.nunique()} subjects in {(time.time() - t0) / 60:.1f} min; "
                f"{n_bad} did not converge")
            out[variant].append(f)
    for variant, parts in out.items():
        path = OUT_DIR / f"stopping_fits_null_snr_{variant}.pkl"
        pd.concat(parts, ignore_index=True).to_pickle(path)
        log(f"wrote {path}")


if __name__ == "__main__":
    main()
