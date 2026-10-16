"""Tests for pigeon.stopping (trial-level stopping model)."""

import numpy as np
import pandas as pd
import pytest

from pigeon.stopping import (KNEE_PARAMS, KNOTS, _knee_log_h, bound_time_course, fit_stopping_model,
                             get_choice_probabilities, get_commit_sources,
                             get_commit_type_probabilities,
                             get_plateau_at_limit, simulate_stopping_data_table,
                             simulate_stopping_trials, stopping_model_nll)

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


def test_fit_recovers_post_change_point_slope():
    d = _sim(4000, 0.01, 10, change_point=4, generative_mean_post=0.01, bound_scale_post=0.25,
             slope_post=-0.06).assign(block_index=3)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, "bound_scale_post": 0.25, "slope_post": -0.06}
    nll_true = stopping_model_nll(d, truth, group_col="block_index")
    assert stopping_model_nll(d, {**truth, "slope_post": 0.0}, group_col="block_index") > nll_true
    p = fit_stopping_model(d, post_params=("bound_scale", "slope"), time_course="flat",
                           smooth_penalty=0.0)["params"].iloc[0]
    assert abs(p["slope_post"] + 0.06) < 0.02
    assert abs(p["bound_scale_post"] - 0.25) < 0.04


def test_fit_recovers_pre_change_point_slope_and_step():
    # Anticipatory tilt anchored at the change point plus a step there: both recovered together.
    d = _sim(4000, 0.01, 11, change_point=10, generative_mean_post=0.03, bound_scale_post=0.14,
             slope_pre=0.05).assign(block_index=3)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, "bound_scale_post": 0.14, "slope_pre": 0.05}
    nll_true = stopping_model_nll(d, truth, group_col="block_index")
    assert stopping_model_nll(d, {**truth, "slope_pre": 0.0}, group_col="block_index") > nll_true
    p = fit_stopping_model(d, post_params=("bound_scale", "pre_slope"), time_course="flat",
                           smooth_penalty=0.0)["params"].iloc[0]
    assert abs(p["slope_pre"] - 0.05) < 0.02
    assert abs(p["bound_scale"] - 0.2) < 0.025
    assert abs(p["bound_scale_post"] - 0.14) < 0.025


def test_fit_recovers_start_anchored_pre_slope_with_varied_change_points():
    # A tilt in elapsed steps (anchored at step 1) with change points from 4 to 13: the anchor matters only
    # when change points vary, and the matching anchor must fit better than the change-point anchor.
    cps = np.random.default_rng(12).integers(4, 14, 4000)
    d = _sim(4000, 0.01, 12, change_point=cps, generative_mean_post=0.03, bound_scale_post=0.14,
             slope_pre=0.04, pre_slope_anchor="start").assign(block_index=3)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, "bound_scale_post": 0.14, "slope_pre": 0.04}
    nll = {a: stopping_model_nll(d, truth, group_col="block_index", pre_slope_anchor=a)
           for a in ("start", "change_point")}
    assert nll["start"] < nll["change_point"]
    p = fit_stopping_model(d, post_params=("bound_scale", "pre_slope"), time_course="flat", smooth_penalty=0.0,
                           pre_slope_anchor="start")["params"].iloc[0]
    assert abs(p["slope_pre"] - 0.04) < 0.015
    assert abs(p["bound_scale"] - 0.2) < 0.025


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


def test_knee_multi_start_keeps_the_best_start():
    # A late knee (7): the fit from several starting knees must do at least as well as every single start.
    d = _sim(1500, 0.02, 17, knee_shape=(0.8, 7.0, -0.01))
    kw = dict(group_col=None, time_course_form="knee", smooth_penalty=0.0)
    multi = fit_stopping_model(d, knee_starts=(2.0, 4.0, 7.0), **kw)
    singles = [fit_stopping_model(d, knee_starts=(k,), **kw)["nll"] for k in (2.0, 4.0, 7.0)]
    assert multi["nll"] <= min(singles) + 1e-6
    assert abs(multi["params"].iloc[0]["knee"] - 7.0) < 1.5


def test_fit_recovers_time_course_per_column_within_a_mixed_group():
    # One block (one set of scale/CV/rates) with trials from two SNRs that differ only in time-course shape.
    lo = _sim(3000, 0.02, 15, knee_shape=(0.9, 4.0, -0.01)).assign(snr_level="lo")
    hi = _sim(3000, 0.04, 16, knee_shape=(0.2, 2.5, -0.03)).assign(snr_level="hi")
    d = pd.concat([lo, hi], ignore_index=True).assign(condition="B1")
    r = fit_stopping_model(d, group_col="condition", time_course_col="snr_level", smooth_penalty=0.0)
    t = r["params"].set_index("time_course_group")
    assert r["success"] and list(t.index) == ["hi", "lo"]
    assert (t["n_trials"] == 3000).all() and t["bound_scale"].nunique() == 1
    assert r["n_params"] == 5 + 1 + 1 + 2 * 3
    # Few commits happen at step 1, so log_h_start trades off against the knee (the best of the multi-start
    # fits here has lo start 1.28, knee 3.6, at lower NLL than the truth's basin); check the shape from step 3.
    steps = np.arange(3, 11)
    for tc, (a, k, sl) in {"lo": (0.9, 4.0, -0.01), "hi": (0.2, 2.5, -0.03)}.items():
        fit = _knee_log_h(*(t.loc[tc, c] for c in KNEE_PARAMS), steps)[0]
        assert np.allclose(fit, _knee_log_h(a, k, sl, steps)[0], atol=0.1)
    assert t.loc["lo", "log_h_start"] > t.loc["hi", "log_h_start"] + 0.4
    assert abs(t.loc["lo", "knee"] - 4.0) < 1.2
    with pytest.raises(ValueError):
        get_commit_type_probabilities(d.assign(subject_index=1), r["params"].assign(subject_index=1),
                                      group_col="condition")


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


def test_plateau_at_limit_flags_both_limits():
    f = pd.DataFrame({"bound_scale": [0.002, 0.00203, 0.05, 1.5, 1.97, 2.0, np.nan]})
    assert get_plateau_at_limit(f).tolist() == [True, True, False, False, True, True, False]


def test_choice_probabilities_are_calibrated():
    d = _sim(20000, 0.03, 18, log_h=COLLAPSE).assign(subject_index=1, condition="B1")  # bins need n >= ~150
    fit = pd.DataFrame([{"subject_index": 1, "group": "B1", **TRUE, "ndt_p1": NDT_PROBS[0], "ndt_p2": NDT_PROBS[1],
                         **{f"log_h_k{k}": v for k, v in zip(KNOTS, COLLAPSE)}}])
    pr = get_choice_probabilities(d, fit)
    assert pr.between(0, 1).all()
    # Calibrated: within bins of predicted P(right), the observed fraction of right choices matches.
    b = pd.cut(pr, [0, 0.1, 0.3, 0.7, 0.9, 1.0], include_lowest=True)
    obs = d.choice.groupby(b, observed=True).mean()
    pred = pr.groupby(b, observed=True).mean()
    assert np.allclose(obs, pred, atol=0.05)
    assert np.corrcoef(pr, d.choice)[0, 1] > 0.6


def test_true_crossed_flags_noise_triggered_commits():
    exact = _sim(3000, 0.02, 19, sensory_std=0.0, guess_rate=0.0)
    lb = exact.commit_type == "bound"
    assert exact.loc[lb, "true_crossed"].all()            # no noise: every bound commit is a true crossing
    noisy = _sim(3000, 0.02, 19, sensory_std=0.1, guess_rate=0.0)
    lb = noisy.commit_type == "bound"
    assert 0.05 < 1 - noisy.loc[lb, "true_crossed"].mean() < 0.95   # noise triggers some commits early
    assert not noisy.loc[noisy.commit_type == "anticipation", "true_crossed"].any()


def test_commit_sources_priority():
    up = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    t = pd.DataFrame({"commit_type": ["guess", "bound", "bound", "bound", "bound", "bound", "anticipation"],
                      "lapse": [True, True, False, False, False, False, False],
                      "DT": [3, 3, 4, 3, 3, 3, 0], "commit_step": [3, 3, 3, 3, 3, 3, 0],
                      "true_crossed": [False, True, True, False, True, True, False],
                      "steps": [up, up, up, up, [0, 0.1, 0.2, -0.1, -0.2, -0.3], up, [0]]})
    assert get_commit_sources(t).tolist() == ["guess", "lapse", "timing", "sensory noise", "measurement",
                                              "collapsing bound", "guess"]


def test_fit_with_fixed_shape_noise_and_ndt():
    knee = (0.8, 3.5, -0.03)
    d = _sim(3000, 0.02, 21, knee_shape=knee)
    fixed = {"log_h_start": knee[0], "knee": knee[1], "sensory_std": TRUE["sensory_std"], "ndt_probs": NDT_PROBS}
    r = fit_stopping_model(d, group_col=None, fixed=fixed)
    p = r["params"].iloc[0]
    assert r["success"] and r["n_params"] == 5 + 1          # five group parameters + the late slope
    assert np.isclose(p["ndt_p1"], NDT_PROBS[0]) and np.isclose(p["knee"], knee[1])
    assert abs(p["late_slope"] - knee[2]) < 0.02
    r0 = fit_stopping_model(d, group_col=None, fixed={**fixed, "late_slope": 0.0})
    assert r0["nll"] > r["nll"] + 2                        # a flat late segment fits worse


def test_simulated_data_table_keeps_trial_order():
    d = pd.DataFrame({"subject_index": 1, "condition": "B1", "block_index": 1, "snr": 0.2, "step_std": 0.1,
                      "trial_number": [12, 10, 11, 15]})
    fit = pd.DataFrame([{"subject_index": 1, "group": "B1", **TRUE, "ndt_p1": NDT_PROBS[0], "ndt_p2": NDT_PROBS[1]}])
    s = simulate_stopping_data_table(d, fit, group_col="condition", num_reps=2, rng=np.random.default_rng(0))
    assert s.trial_number.tolist() == [12, 10, 11, 15] * 2 and s.rep.tolist() == [0] * 4 + [1] * 4
