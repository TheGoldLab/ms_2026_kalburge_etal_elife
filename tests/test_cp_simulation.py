"""Tests for the change-point simulator in pigeon.simulation."""

import numpy as np
import pandas as pd

from pigeon.simulation import get_simulated_cp_data_table, simulate_cp_trials

NO_NOISE = 1e-12  # effectively deterministic walks


def test_drift_switches_before_the_cp_step_th_movement():
    # Bound far out of reach, so every trial runs all 50 positions.
    sim = simulate_cp_trials(
        0.01,
        0.03,
        NO_NOISE,
        cp_step=6,
        num_trials=20,
        bound_pre=5.0,
        rng=np.random.default_rng(0),
    )
    for steps, snr in zip(sim["steps"], sim["snr"]):
        moves = np.diff(steps) * np.sign(snr)
        assert np.allclose(moves[:5], 0.01)  # movements 1-5: starting SNR
        assert np.allclose(moves[5:], 0.03)  # movements 6+: new SNR
    assert np.all(np.isnan(sim["choice"]))  # no crossing -> no choice


def test_no_switch_without_cp_step():
    sim = simulate_cp_trials(
        0.01,
        0.03,
        NO_NOISE,
        cp_step=None,
        num_trials=5,
        bound_pre=5.0,
        rng=np.random.default_rng(0),
    )
    for steps, snr in zip(sim["steps"], sim["snr"]):
        assert np.allclose(np.diff(steps) * np.sign(snr), 0.01)


def test_post_bound_applies_after_the_switch():
    # Position after j movements = 0.01 j. With bound_post = 0.095 from the switch
    # (cp = 5) on, the crossing is at j = 10; without adaptation (0.5) never.
    kw = {
        "pre_mean": 0.01,
        "post_mean": 0.01,
        "generative_std": NO_NOISE,
        "cp_step": 5,
        "num_trials": 10,
        "bound_pre": 0.5,
        "ndt": 2,
    }
    adapted = simulate_cp_trials(**kw, bound_post=0.095, rng=np.random.default_rng(1))
    assert np.all(adapted["RT"] == 10 + 2 + 1)  # crossing index + NDT + 1
    assert np.all([len(s) == rt for s, rt in zip(adapted["steps"], adapted["RT"])])
    assert np.allclose(adapted["bound"], 0.095)
    same = simulate_cp_trials(**kw, rng=np.random.default_rng(1))
    assert np.all(np.isnan(same["choice"]))


def test_choice_and_correct_coding():
    sim = simulate_cp_trials(
        0.03,
        0.03,
        NO_NOISE,
        cp_step=None,
        num_trials=200,
        bound_pre=0.1,
        rng=np.random.default_rng(2),
    )
    right = sim["snr"] > 0
    assert np.all(sim["choice"][right] == 1) and np.all(sim["choice"][~right] == 0)
    assert np.all(sim["correct"] == 1)
    assert 0 < right.sum() < 200  # both directions occur


def _real_like_table():
    """Two subjects, four canonical blocks, the fields the simulator reads."""
    rows = []
    for subj, cps in ((1, (6, 4)), (2, (9, 7))):
        for block, mean, cp in (
            (1, 0.01, 0),
            (2, 0.03, 0),
            (3, 0.01, cps[0]),
            (4, 0.03, cps[1]),
        ):
            for tt in range(1, 41):
                rows.append(
                    {
                        "subject_index": subj,
                        "block_index": block,
                        "trial_number": tt,
                        "snr": (-1) ** tt * mean / 0.05,
                        "step_std": 0.05,
                        "bound": 0.12 if block in (1, 3) else 0.18,
                        "RT": 12.0,
                        "DT": 10.0,
                        "change_point": float(cp),
                        "correct": 1.0,
                        "wall_hit": False,
                        "rt_below_cutoff": False,
                    }
                )
    return pd.DataFrame(rows)


def test_simulated_cohort_matches_real_structure():
    real = _real_like_table()
    sim = get_simulated_cp_data_table(
        real, bound_std=0.02, correct_bias=None, rng=np.random.default_rng(3)
    )
    counts = sim.groupby(["subject_index", "block_index"]).size()
    assert (counts == 40).all() and len(counts) == 8
    cps = sim.groupby(["subject_index", "block_index"])["change_point"].first()
    assert cps.loc[(1, 3)] == 6 and cps.loc[(2, 4)] == 7 and cps.loc[(1, 1)] == 0
    snrs = sim.groupby("block_index")["snr"].apply(
        lambda s: sorted(np.unique(np.abs(s).round(6)))
    )
    assert snrs.loc[3] == [0.2] and snrs.loc[4] == [
        0.6
    ]  # snr = starting SNR, as in real data
    for col in ("bound", "DT", "RT", "rt_cutoff", "wall_hit", "abs_bound"):
        assert col in sim.columns


def test_simulated_cohort_is_reproducible():
    real = _real_like_table()
    a = get_simulated_cp_data_table(
        real, correct_bias=None, rng=np.random.default_rng(4)
    )
    b = get_simulated_cp_data_table(
        real, correct_bias=None, rng=np.random.default_rng(4)
    )
    assert np.array_equal(a["RT"], b["RT"]) and np.allclose(
        a["bound"], b["bound"], equal_nan=True
    )
