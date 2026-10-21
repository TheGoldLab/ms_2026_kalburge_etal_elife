"""Power, trial counts and coins for the RC (reward change) task under one cost scheme.

Synthetic participants are MXSC participants' block-1 stopping-model fits (low SNR, fixed
reward; stage 1 of Figure 6, ``stopping_fits_cp_plateau_pair.pkl``; edge fits left out of the
pool), drawn with replacement into cohorts. Each runs the four 1000-step RC blocks at the RC
difficulty (step mean 0.01, SD 0.05):

    F1 (+1/-1), F3 (+3/-3), LH (rising: +1/-1 then +3/-3), HL (falling: the reverse).

In F1 and F3 the participant keeps the fitted bound (the ideal policy is the same in both). In
LH and HL the log bound moves by ``alpha`` times the ideal observer's change-specific
adjustment (pigeon.ideal_observer.get_optimal_bounds), projected onto the matched analysis's
form:

    log r(j) = log(b*_change(j) / b*_fixed), clipped to [log 1/4, log 4]
               ("never respond" -> log 4; a bound of ~0 -> log 1/4)
    before the switch (j < cp): a + s (j - cp), least squares over j = 1..cp-1
    from the switch on (j >= cp): c, the mean over j = cp..cp+9

so the generator uses bound_scale = base e^{alpha a}, slope_pre = alpha s and bound_scale_post =
base e^{alpha c}. alpha = 0 is the null (change blocks run like the fixed blocks); alpha = 1
moves the bound as far as the ideal observer does, relative to the participant's own bound.

Task rules as in task/RC: the switch step cp is the participant's median RT over F1 and F3
(first 10 trials of each dropped); steps used per trial = RT + start_cost + error_cost per
error; a trial with no commit by step 50 times out (50 steps, no choice, no coins); a response
earns the coins in force at its last shown position (index RT - 1).

Analysis = stage 2 of Figure 6 (run_stopping_fits_cp_matched.py): CV, guess, lapse and
anticipation rates, sensory noise, NDT and the bound's shape fixed at their TRUE values (so the
power is an upper bound); free per block: the pre-switch plateau, the post-switch plateau and
the pre-switch tilt; the fixed blocks get the switch step as a pseudo change point; trials 1-9
are dropped. Per participant, change block minus matched fixed block (LH - F1, HL - F3):

    level = log(bound_scale)       (the pre-switch bound at the switch)
    tilt  = slope_pre
    step  = log(bound_scale_post / bound_scale)

Each effect is tested across the cohort's participants (Wilcoxon signed-rank, two-sided);
participants with an edge fit in any block (pigeon.stopping.get_plateau_edge_fit) are left out
and counted.

Writes data/processed/rc_power_s<start>_e<error>.pkl (one row per cohort and alpha: medians and
p values) and rc_blocks_s<start>_e<error>.pkl (one row per synthetic participant and block:
trials, coins, accuracy, timeouts, switch step). Run from the project root (about 35 s per
cohort of 60 on 10 cores):

    nohup caffeinate -i uv run python scripts/run_rc_power.py --start-cost 1 --error-cost 15 \\
        > data/processed/rc_power_s1_e15.log 2>&1 &
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats

from pigeon.ideal_observer import MAX_STEPS, RC_STEP_MEAN, RC_STEP_STD, get_optimal_bounds
from pigeon.stopping import KNEE_PARAMS, fit_stopping_models, get_plateau_edge_fit, simulate_stopping_trials

DATA_DIR = Path("data/processed")
BUDGET = 1000
LOW, HIGH = (1, 1), (3, 3)
BLOCKS = {"F1": (LOW, LOW), "F3": (HIGH, HIGH), "LH": (LOW, HIGH), "HL": (HIGH, LOW)}
MATCHED = {"LH": "F1", "HL": "F3"}
LOG_CLIP = np.log(4.0)
NUISANCE = ("bound_cv", "guess_rate", "lapse_rate", "anticipation_rate")
SWITCH_RANGE = (2, 40)


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def load_pool():
    """MXSC block-1 stage-1 fits that converged and are not edge fits."""
    f = pd.read_pickle(DATA_DIR / "stopping_fits_cp_plateau_pair.pkl")
    b1 = f[(f["group"] == "B1") & f["success"].astype(bool)]
    return b1[~get_plateau_edge_fit(b1)].reset_index(drop=True)


def get_optimal_adjustments(start_cost, error_cost, switch_steps):
    """
    Ideal observer's change-specific log adjustment, projected onto (a, s, c).

    Returns the fixed-block optimal bound and {switch_step: {'LH': (a, s, c), 'HL': (a, s, c)}}.
    """
    _, fixed = get_optimal_bounds(LOW, start_cost=start_cost, error_cost=error_cost)
    b_fixed = np.nanmedian(fixed[1:30])  # flat apart from the drop near the timeout
    out = {}
    for cp in switch_steps:
        out[cp] = {}
        for name in ("LH", "HL"):
            _, b = get_optimal_bounds(*BLOCKS[name], cp, start_cost=start_cost, error_cost=error_cost)
            lr = np.clip(np.log(np.where(np.isnan(b), np.inf, np.maximum(b, 1e-9)) / b_fixed), -LOG_CLIP, LOG_CLIP)
            j = np.arange(1, cp)
            s, a = np.polyfit(j - cp, lr[1:cp], 1) if len(j) >= 2 else (0.0, float(lr[1]))
            c = float(lr[cp : min(cp + 10, MAX_STEPS)].mean())
            out[cp][name] = (float(a), float(s), c)
    return b_fixed, out


def simulate_block(p, rng, switch_step, adjustment, alpha, start_cost, error_cost, reward):
    """One 1000-step block of a synthetic participant (trials until the step budget runs out)."""
    a, s, c = adjustment
    sim = simulate_stopping_trials(
        400,  # more than any participant completes in 1000 steps
        RC_STEP_MEAN,
        RC_STEP_STD,
        p["bound_scale"] * np.exp(alpha * a),
        p["bound_cv"],
        p["guess_rate"],
        p["lapse_rate"],
        p["anticipation_rate"],
        p["sensory_std"],
        ndt_probs=(p["ndt_p1"], p["ndt_p2"]),
        knee_shape=tuple(p[k] for k in KNEE_PARAMS),
        change_point=switch_step,
        bound_scale_post=p["bound_scale"] * np.exp(alpha * c),
        slope_pre=alpha * s,
        max_steps=MAX_STEPS + 3,  # a commit after step 50 ('cap') is a timeout
        rng=rng,
    )
    timeout = (sim["commit_type"] == "cap").to_numpy()
    rt = np.where(timeout, MAX_STEPS, sim["RT"].to_numpy())
    error = (sim["correct"].to_numpy() == 0) & ~timeout
    n = int(np.searchsorted(np.cumsum(rt + start_cost + error_cost * error), BUDGET, side="right"))
    sim = sim.iloc[:n].copy()
    sim["timeout"] = timeout[:n]
    (gain_pre, loss_pre), (gain_post, loss_post) = reward
    post = (sim["RT"].to_numpy() - 1) >= switch_step
    gain, loss = np.where(post, gain_post, gain_pre), np.where(post, loss_post, loss_pre)
    sim["coins"] = np.where(sim["timeout"], 0, np.where(sim["correct"] == 1, gain, -loss))
    sim["trial_number"] = np.arange(1, n + 1)
    return sim


def simulate_participant(p, rng, adjustments, alpha, start_cost, error_cost):
    """The four blocks of one synthetic participant; the switch step comes from their fixed blocks."""
    blocks = {
        name: simulate_block(p, rng, 0, (0.0, 0.0, 0.0), 0.0, start_cost, error_cost, BLOCKS[name])
        for name in ("F1", "F3")
    }
    pooled = pd.concat([d[(d["trial_number"] > 10) & ~d["timeout"]] for d in blocks.values()])
    switch_step = int(np.clip(np.median(pooled["RT"]), *SWITCH_RANGE)) if len(pooled) else 10
    for name in ("LH", "HL"):
        blocks[name] = simulate_block(
            p, rng, switch_step, adjustments[switch_step][name], alpha, start_cost, error_cost, BLOCKS[name]
        )
    trials = pd.concat([d.assign(condition=name) for name, d in blocks.items()], ignore_index=True)
    trials["change_point"] = float(switch_step)  # pseudo change point in the fixed blocks
    return switch_step, trials


def fit_cohort(trials, truth):
    """Stage-2 matched fit with the nuisance parameters fixed at each participant's true values."""
    d = trials[(trials["trial_number"] >= 10) & ~trials["timeout"]].copy()
    subject_kwargs = {}
    for si, p in truth.items():
        fixed = {name: np.full(len(BLOCKS), p[name]) for name in NUISANCE}
        fixed["sensory_std"] = float(p["sensory_std"])
        fixed["ndt_probs"] = np.array([p["ndt_p1"], p["ndt_p2"]])
        fixed.update({name: np.array([p[name]]) for name in KNEE_PARAMS})
        subject_kwargs[si] = {"fixed": fixed}
    return fit_stopping_models(
        d,
        group_col="condition",
        subject_kwargs=subject_kwargs,
        post_params=("bound_scale", "pre_slope"),
        pre_slope_anchor="change_point",
        smooth_penalty=0.0,
    )


def get_effects(fits):
    """Cohort medians and Wilcoxon p values of level, tilt and step (change minus matched fixed block)."""
    edge = get_plateau_edge_fit(fits.assign(bound_scale=fits[["bound_scale", "bound_scale_post"]].max(axis=1)))
    bad = set(fits.loc[edge | ~fits["success"].astype(bool), "subject_index"])
    f = fits[~fits["subject_index"].isin(bad)].set_index(["subject_index", "group"])
    out = {"n_excluded": len(bad)}
    for change, fixed in MATCHED.items():
        ch, fx = f.xs(change, level="group"), f.xs(fixed, level="group")
        values = {
            "level": np.log(ch["bound_scale"] / fx["bound_scale"]),
            "tilt": ch["slope_pre"] - fx["slope_pre"],
            "step": np.log(ch["bound_scale_post"] / ch["bound_scale"])
            - np.log(fx["bound_scale_post"] / fx["bound_scale"]),
        }
        for name, v in values.items():
            out[f"{change}_{name}_median"] = float(np.median(v))
            out[f"{change}_{name}_p"] = float(scipy.stats.wilcoxon(v).pvalue) if len(v) > 5 else np.nan
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start-cost", type=int, required=True)
    parser.add_argument("--error-cost", type=int, required=True)
    parser.add_argument("--n-cohorts", type=int, default=20)
    parser.add_argument("--n-participants", type=int, default=60)
    parser.add_argument("--alphas", type=float, nargs="+", default=[0.0, 0.25, 0.5])
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    pool = load_pool()
    b_fixed, adjustments = get_optimal_adjustments(
        args.start_cost, args.error_cost, range(SWITCH_RANGE[0], SWITCH_RANGE[1] + 1)
    )
    tag = f"s{args.start_cost}_e{args.error_cost}"
    log(
        f"{tag}: pool of {len(pool)} MXSC fits; ideal fixed-block bound {b_fixed:.3f}; adjustment at switch 9 {adjustments[9]}"
    )
    cohort_rows, block_rows = [], []
    for alpha in args.alphas:
        for ci in range(args.n_cohorts):
            rng = np.random.default_rng([args.seed, ci, round(100 * alpha)])
            trials, truth = [], {}
            for si, pi in enumerate(rng.choice(len(pool), args.n_participants, replace=True)):
                p = pool.iloc[pi]
                switch_step, t = simulate_participant(p, rng, adjustments, alpha, args.start_cost, args.error_cost)
                truth[si] = p
                trials.append(t.assign(subject_index=si))
                for name, d in t.groupby("condition"):
                    responded = ~d["timeout"]
                    block_rows.append(
                        {
                            "scheme": tag,
                            "alpha": alpha,
                            "cohort": ci,
                            "participant": si,
                            "pool_index": int(pi),
                            "block": name,
                            "switch_step": switch_step,
                            "n_trials": len(d),
                            "n_fit": int(((d["trial_number"] >= 10) & responded).sum()),
                            "coins": int(d["coins"].sum()),
                            "accuracy": d.loc[responded, "correct"].mean(),
                            "timeouts": d["timeout"].mean(),
                        }
                    )
            t0 = time.time()
            fits = fit_cohort(pd.concat(trials, ignore_index=True), truth)
            cohort_rows.append({"scheme": tag, "alpha": alpha, "cohort": ci, **get_effects(fits)})
            log(f"{tag} alpha {alpha} cohort {ci}: fit in {time.time() - t0:.0f} s")
            pd.DataFrame(cohort_rows).to_pickle(DATA_DIR / f"rc_power_{tag}.pkl")
            pd.DataFrame(block_rows).to_pickle(DATA_DIR / f"rc_blocks_{tag}.pkl")


if __name__ == "__main__":
    main()
