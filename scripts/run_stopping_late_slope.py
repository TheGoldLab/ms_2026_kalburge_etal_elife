"""Does the bound keep falling after its initial collapse, in each condition?

For every subject and condition (OL raw blocks 1-6; MX blocks 1-3 split by
SNR), fits the stopping model to that condition's trials alone with the
subject's start height, time of fall, sensory noise and NDT distribution fixed
at their main fit (data/processed/stopping_fits_main.pkl). Free: the
condition's plateau, bound CV, guess, lapse and anticipation rates, and the
slope of the bound after the fall (late_slope). The null model is the same
with late_slope fixed at 0 (bound flat after the fall). No smoothing penalty,
so 2 * (nll_null - nll_alt) is a likelihood-ratio statistic (chi-square, 1 df).

Writes data/processed/stopping_late_slope.pkl, one row per subject x
condition, for notebooks/Figure05S01_collapseByCondition.ipynb. Run from the
project root:

    PYTHONPATH=. nohup uv run python scripts/run_stopping_late_slope.py > data/processed/stopping_late_slope.log 2>&1 &
"""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats

from pigeon.stopping import fit_stopping_model, get_stopping_model_trials

OUT = Path("data/processed/stopping_late_slope.pkl")
DATASETS = {"OL": [1, 2, 3, 4, 5, 6], "MX": [1, 2, 3]}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def job(args):
    task, subject, condition, d, fixed = args
    row = {"task": task, "subject_index": subject, "condition": condition, "n_trials": len(d)}
    try:
        alt = fit_stopping_model(d, group_col=None, fixed=fixed, smooth_penalty=0.0)
        null = fit_stopping_model(d, group_col=None, fixed={**fixed, "late_slope": 0.0}, smooth_penalty=0.0)
    except Exception as err:  # report per-condition failures instead of losing the run
        return {**row, "error": repr(err)}
    p = alt["params"].iloc[0]
    lr = max(2 * (null["nll"] - alt["nll"]), 0.0)
    return {**row, "late_slope": p["late_slope"], "bound_scale": p["bound_scale"],
            "bound_scale_null": null["params"].iloc[0]["bound_scale"],
            "nll_alt": alt["nll"], "nll_null": null["nll"], "lr_stat": lr, "p_value": scipy.stats.chi2.sf(lr, 1),
            "success_alt": alt["success"], "success_null": null["success"], "error": None}


def main():
    fits = pd.read_pickle("data/processed/stopping_fits_main.pkl")
    jobs = []
    for task, blocks in DATASETS.items():
        d_task = get_stopping_model_trials(task, blocks)
        if task == "MX":
            lo = np.isclose(d_task["snr"].abs(), d_task["snr"].abs().min())
            d_task["condition"] = d_task["condition"] + np.where(lo, "_lo", "_hi")
        f_task = fits[fits.task == task].groupby("subject_index").first()
        for (subject, condition), d in d_task.groupby(["subject_index", "condition"]):
            f = f_task.loc[subject]
            fixed = {"log_h_start": f.log_h_start, "knee": f.knee, "sensory_std": f.sensory_std,
                     "ndt_probs": [f.ndt_p1, f.ndt_p2]}
            jobs.append((task, subject, condition, d, fixed))
    log(f"{len(jobs)} subject x condition fits (x2: alternative and null)")
    t0 = time.time()
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(job, jobs, chunksize=4))
    out = pd.DataFrame(rows)
    out.to_pickle(OUT)
    log(f"done in {(time.time() - t0) / 60:.1f} min; {int(out.error.notna().sum())} raised; "
        f"not converged: alt {int((out.success_alt == False).sum())}, null {int((out.success_null == False).sum())}; "  # noqa: E712
        f"wrote {OUT}")


if __name__ == "__main__":
    main()
