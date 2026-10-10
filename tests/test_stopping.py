"""Tests for pigeon.stopping (trial-level stopping model)."""

import numpy as np
import pandas as pd
import pytest

from pigeon.stopping import (KNOTS, bound_time_course, fit_stopping_model, get_commit_type_probabilities,
                             get_effective_bounds, simulate_stopping_trials, stopping_model_nll)

TRUE = dict(bound_scale=0.2, bound_cv=0.3, guess_rate=0.03, lapse_rate=0.04, anticipation_rate=0.03,
            sensory_std=0.02)
NDT_PROBS = (0.7, 0.3)
COLLAPSE = np.array([0.3, 0.0, -0.4])   # log h at KNOTS (1, 6, 16); 0 at the anchor (step 6)


def _sim(n, gm, seed, **kw):
    params = {**TRUE, **kw}
    return simulate_stopping_trials(n, gm, 0.05, ndt_probs=NDT_PROBS, rng=np.random.default_rng(seed), **params)


def test_simulated_trials_follow_rt_convention():
    d = _sim(2000, 0.02, 0)
    assert (d["steps"].apply(len) == d["RT"]).all()
    assert (d["steps"].apply(lambda s: s[0]) == 0).all()
    lc = d["commit_type"] != "anticipation"
    assert (d.loc[lc, "RT"] == d.loc[lc, "commit_step"] + d.loc[lc, "ndt"] + 1).all()
    assert (d.loc[~lc, "RT"] == 1).all()
    assert (d.loc[lc, "RT"] >= 2).all()


def test_nll_is_lower_at_truth_than_perturbed():
    d = _sim(3000, 0.02, 1, log_h=COLLAPSE)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, "log_h": COLLAPSE}
    nll_true = stopping_model_nll(d, truth, group_col=None)
    for name, val in [("bound_scale", 0.28), ("bound_cv", 0.1), ("guess_rate", 0.1),
                      ("sensory_std", 0.08), ("log_h", np.zeros(3))]:
        assert stopping_model_nll(d, {**truth, name: val}, group_col=None) > nll_true


def test_zero_sensory_noise_is_exact_crossing():
    d = _sim(500, 0.02, 2, sensory_std=0.0)
    nll = stopping_model_nll(d, {**TRUE, "sensory_std": 0.0, "ndt_probs": NDT_PROBS}, group_col=None)
    assert np.isfinite(nll)


def test_fit_recovers_parameters_and_time_course():
    d = _sim(4000, 0.02, 3, log_h=COLLAPSE)
    r = fit_stopping_model(d, group_col=None, smooth_penalty=0.0, time_course_form="knots")
    p = r["params"].iloc[0]
    assert r["success"]
    assert abs(p["bound_scale"] - TRUE["bound_scale"]) < 0.02
    assert abs(p["guess_rate"] - TRUE["guess_rate"]) < 0.01
    assert abs(p["sensory_std"] - TRUE["sensory_std"]) < 0.01
    assert abs(p["ndt_p1"] - NDT_PROBS[0]) < 0.06
    fitted = bound_time_course(p, KNOTS)
    true = TRUE["bound_scale"] * np.exp(COLLAPSE)
    assert np.all(np.abs(fitted - true) < 0.03)


def test_fit_recovers_change_point_shift():
    d = pd.concat([
        _sim(2500, 0.01, 4, change_point=6, generative_mean_post=0.03, bound_scale_post=0.13).assign(block_index=3),
        _sim(2500, 0.03, 5, change_point=6, generative_mean_post=0.01, bound_scale_post=0.28).assign(block_index=4),
    ], ignore_index=True)
    p = fit_stopping_model(d, post_params=("bound_scale",), time_course="flat")["params"].set_index("group")
    assert abs(p.loc[3, "bound_scale_post"] - 0.13) < 0.025
    assert abs(p.loc[4, "bound_scale_post"] - 0.28) < 0.04
    assert abs(p.loc[3, "bound_scale"] - 0.2) < 0.025


def test_wall_hit_trials_are_censored_not_misfit():
    # Large steps: many trials reach the wall; the fit should still recover the bound.
    d = simulate_stopping_trials(3000, 0.15, 0.3, 0.4, 0.35, guess_rate=0.02, ndt_probs=NDT_PROBS,
                                 rng=np.random.default_rng(6))
    assert d["wall_hit"].mean() > 0.2
    r = fit_stopping_model(d, group_col=None, time_course="flat", fixed={"sensory_std": 0.0})
    assert abs(r["params"]["bound_scale"].iloc[0] - 0.4) < 0.04


def test_groups_without_post_data_report_nan_post():
    d = pd.concat([_sim(300, 0.01, 7).assign(block_index=1),
                   _sim(300, 0.01, 8, change_point=6, generative_mean_post=0.03).assign(block_index=3)],
                  ignore_index=True)
    p = fit_stopping_model(d, post_params=("bound_scale",), time_course="flat")["params"].set_index("group")
    assert np.isnan(p.loc[1, "bound_scale_post"]) and np.isfinite(p.loc[3, "bound_scale_post"])


def test_fit_rejects_missing_choices():
    d = _sim(50, 0.02, 9)
    d.loc[0, "choice"] = np.nan
    with pytest.raises(ValueError, match="missing choice"):
        fit_stopping_model(d, group_col=None)


def test_shared_and_per_block_parameters():
    d = pd.concat([_sim(400, 0.01, 10, bound_scale=0.25).assign(block_index=1),
                   _sim(400, 0.03, 11, bound_scale=0.15).assign(block_index=2)], ignore_index=True)
    # Default: all five group parameters per block; knee time course (3), noise, NDT shared.
    r = fit_stopping_model(d)
    assert r["params"]["guess_rate"].nunique() == 2
    assert r["n_params"] == 2 * 5 + 3 + 1 + 1   # 5 per block; start, knee, late slope; noise; NDT
    # Sharing the three rates.
    r = fit_stopping_model(d, time_course="flat", shared_params=("guess_rate", "lapse_rate", "anticipation_rate"))
    p = r["params"]
    assert p["guess_rate"].nunique() == 1 and p["lapse_rate"].nunique() == 1
    assert p["bound_scale"].nunique() == 2
    assert r["n_params"] == 2 * 2 + 3 + 1 + 1   # scale, cv per block; 3 rates; noise; NDT


def test_effective_bounds_match_time_course():
    fit = {"subject_index": 1, "group": "B1", "bound_scale": 0.2, "ndt_p1": 0.7, "ndt_p2": 0.3,
           **{f"log_h_k{k}": v for k, v in zip(KNOTS, COLLAPSE)}}
    d = pd.DataFrame({"subject_index": 1, "condition": "B1", "RT": [2, 5, 9, 30]})
    got = get_effective_bounds(d, pd.DataFrame([fit]))
    want = [0.7 * bound_time_course(fit, [max(rt - 2, 1)])[0] + 0.3 * bound_time_course(fit, [max(rt - 3, 1)])[0]
            for rt in d.RT]
    assert np.allclose(got, want)


def test_fit_recovers_guess_time_course_with_flat_bound():
    early = np.array([1.5, 0.0, -0.5])   # logit-scale guess shift at KNOTS: more guessing early
    d = _sim(4000, 0.02, 12, log_g=early, guess_rate=0.04)
    truth = {**TRUE, "guess_rate": 0.04, "ndt_probs": NDT_PROBS, "log_g": early}
    nll_true = stopping_model_nll(d, truth, group_col=None)
    assert stopping_model_nll(d, {**truth, "log_g": np.zeros(3)}, group_col=None) > nll_true
    r = fit_stopping_model(d, group_col=None, time_course="flat", guess_time_course="shared", smooth_penalty=0.0)
    p = r["params"].iloc[0]
    assert r["success"]
    assert abs(p["bound_scale"] - TRUE["bound_scale"]) < 0.02
    assert abs(p["log_g_k1"] - early[0]) < 0.4
    assert abs(p["log_g_k16"] - early[2]) < 0.5


def test_fit_recovers_knee_time_course():
    knee = (0.8, 3.5, -0.01)   # bound 2.2x higher at step 1, knee at step 3.5, slight late decline
    d = _sim(4000, 0.02, 13, knee_shape=knee)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, **dict(zip(("log_h_start", "knee", "late_slope"), knee))}
    nll_true = stopping_model_nll(d, truth, group_col=None)
    assert stopping_model_nll(d, {**truth, "knee": 7.0}, group_col=None) > nll_true
    r = fit_stopping_model(d, group_col=None, time_course_form="knee", smooth_penalty=0.0)
    p = r["params"].iloc[0]
    assert r["success"]
    assert abs(p["knee"] - knee[1]) < 1.0
    assert abs(p["log_h_start"] - knee[0]) < 0.3
    assert abs(p["bound_scale"] - TRUE["bound_scale"]) < 0.02
    steps = np.arange(1, 20)
    assert np.allclose(bound_time_course(p, steps), TRUE["bound_scale"] * np.exp(
        np.where(steps < knee[1], knee[0] * (knee[1] - steps) / (knee[1] - 1), knee[2] * (steps - knee[1]))),
        atol=0.04)


def test_commit_type_probabilities_are_calibrated():
    d = _sim(6000, 0.02, 14, guess_rate=0.06, log_h=COLLAPSE).assign(subject_index=1, condition="B1")
    fit = pd.DataFrame([{"subject_index": 1, "group": "B1", **TRUE, "guess_rate": 0.06,
                         "ndt_p1": NDT_PROBS[0], "ndt_p2": NDT_PROBS[1],
                         **{f"log_h_k{k}": v for k, v in zip(KNOTS, COLLAPSE)}}])
    pg = get_commit_type_probabilities(d, fit)
    ok = pg.notna()
    is_guess = d.commit_type.isin(["guess", "anticipation"])
    # Posterior probabilities average to the true fraction, overall and within true types' ordering.
    assert abs(pg[ok].mean() - is_guess[ok].mean()) < 0.015
    assert pg[ok & is_guess].mean() > pg[ok & ~is_guess].mean() + 0.3
