"""Tests for pigeon.stopping (trial-level stopping model)."""

import numpy as np
import pandas as pd
import pytest

from pigeon.stopping import (KNOTS, bound_time_course, fit_stopping_model, simulate_stopping_trials,
                             stopping_model_nll)

TRUE = dict(bound_scale=0.2, bound_cv=0.3, guess_rate=0.03, lapse_rate=0.04, anticipation_rate=0.03,
            sensory_std=0.02)
NDT_PROBS = (0.7, 0.3)
COLLAPSE = np.array([0.0, -0.1, -0.3, -0.5, -0.7])


def _sim(n, gm, seed, **kw):
    params = {**TRUE, **kw}
    return simulate_stopping_trials(n, gm, 0.05, ndt_probs=NDT_PROBS, rng=np.random.default_rng(seed), **params)


def test_simulated_trials_follow_rt_convention():
    d = _sim(2000, 0.02, 0)
    assert (d["steps"].apply(len) == d["RT"]).all()
    assert (d["steps"].apply(lambda s: s[0]) == 0).all()
    lc = d["commit_type"] != "anticipation"
    assert (d.loc[lc, "RT"] == d.loc[lc, "commit_step"] + d.loc[lc, "ndt"] + 1).all()
    assert (d.loc[~lc, "RT"] <= d.loc[~lc, "ndt"] + 1).all()


def test_nll_is_lower_at_truth_than_perturbed():
    d = _sim(3000, 0.02, 1, log_h=COLLAPSE)
    truth = {**TRUE, "ndt_probs": NDT_PROBS, "log_h": COLLAPSE}
    nll_true = stopping_model_nll(d, truth, group_col=None)
    for name, val in [("bound_scale", 0.28), ("bound_cv", 0.1), ("guess_rate", 0.1),
                      ("sensory_std", 0.08), ("log_h", np.zeros(5))]:
        assert stopping_model_nll(d, {**truth, name: val}, group_col=None) > nll_true


def test_zero_sensory_noise_is_exact_crossing():
    d = _sim(500, 0.02, 2, sensory_std=0.0)
    nll = stopping_model_nll(d, {**TRUE, "sensory_std": 0.0, "ndt_probs": NDT_PROBS}, group_col=None)
    assert np.isfinite(nll)


def test_fit_recovers_parameters_and_time_course():
    d = _sim(4000, 0.02, 3, log_h=COLLAPSE)
    r = fit_stopping_model(d, group_col=None)
    p = r["params"].iloc[0]
    assert r["success"]
    assert abs(p["bound_scale"] - TRUE["bound_scale"]) < 0.02
    assert abs(p["guess_rate"] - TRUE["guess_rate"]) < 0.01
    assert abs(p["sensory_std"] - TRUE["sensory_std"]) < 0.01
    assert abs(p["ndt_p1"] - NDT_PROBS[0]) < 0.06
    fitted = bound_time_course(p, KNOTS)
    true = TRUE["bound_scale"] * np.exp(COLLAPSE)
    assert np.all(np.abs(fitted[:4] - true[:4]) < 0.02)   # knot 16 is sparsely sampled


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
