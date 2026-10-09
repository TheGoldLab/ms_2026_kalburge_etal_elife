"""Tests for pigeon.stopping (trial-level stopping model)."""

import numpy as np
import pandas as pd
import pytest

from pigeon.stopping import fit_stopping_model, simulate_stopping_trials, stopping_model_nll

TRUE = dict(bound_mean=0.15, bound_std=0.07, guess_rate=0.03, lapse_rate=0.05, anticipation_rate=0.03)
NDT_PROBS = (0.7, 0.2, 0.1)


def _sim(n, gm, seed, **kw):
    params = {**TRUE, **kw}
    return simulate_stopping_trials(n, gm, 0.05, ndt_probs=NDT_PROBS, rng=np.random.default_rng(seed), **params)


def test_simulated_trials_follow_rt_convention():
    d = _sim(2000, 0.02, 0)
    assert (d["steps"].apply(len) == d["RT"]).all()
    assert (d["steps"].apply(lambda s: s[0]) == 0).all()
    lc = d["commit_type"] != "anticipation"
    assert (d.loc[lc, "RT"] == d.loc[lc, "commit_step"] + d.loc[lc, "ndt"] + 1).all()
    la = ~lc
    assert (d.loc[la, "RT"] <= d.loc[la, "ndt"] + 1).all()
    # Non-lapse bound commits choose the side the pigeon is on at the commit step.
    side = np.array([np.sign(s[k]) for s, k in zip(d["steps"], d["commit_step"])])
    lb = (d["commit_type"] == "bound").to_numpy()
    assert np.mean((side[lb] > 0) == (d.loc[lb, "choice"] == 1)) > 0.95


def test_nll_is_lower_at_truth_than_perturbed():
    d = _sim(3000, 0.02, 1)
    nll_true = stopping_model_nll(d, TRUE, NDT_PROBS, group_col=None)
    for name, val in [("bound_mean", 0.22), ("bound_std", 0.02), ("guess_rate", 0.1), ("lapse_rate", 0.2)]:
        assert stopping_model_nll(d, {**TRUE, name: val}, NDT_PROBS, group_col=None) > nll_true


def test_fit_recovers_parameters():
    d = pd.concat([_sim(3000, 0.01, 2).assign(block_index=1), _sim(3000, 0.03, 3).assign(block_index=2)],
                  ignore_index=True)
    r = fit_stopping_model(d)
    assert r["success"]
    p = r["params"]
    assert np.allclose(p["bound_mean"], TRUE["bound_mean"], atol=0.01)
    assert np.allclose(p["bound_std"], TRUE["bound_std"], atol=0.01)
    assert np.allclose(p["guess_rate"], TRUE["guess_rate"], atol=0.01)
    assert np.allclose(p["anticipation_rate"], TRUE["anticipation_rate"], atol=0.015)
    assert abs(r["ndt_probs"][1] - NDT_PROBS[0]) < 0.05


def test_fit_recovers_change_point_shift():
    d = pd.concat([
        _sim(3000, 0.01, 4, change_point=6, generative_mean_post=0.03, bound_mean_post=0.10).assign(block_index=3),
        _sim(3000, 0.03, 5, change_point=6, generative_mean_post=0.01, bound_mean_post=0.20).assign(block_index=4),
    ], ignore_index=True)
    p = fit_stopping_model(d, post_params=("bound_mean",))["params"].set_index("group")
    assert abs(p.loc[3, "bound_mean_post"] - 0.10) < 0.02
    assert abs(p.loc[4, "bound_mean_post"] - 0.20) < 0.03
    assert abs(p.loc[3, "bound_mean"] - 0.15) < 0.02


def test_wall_hit_trials_are_censored_not_misfit():
    # Large steps: many trials reach the wall; the fit should still recover the bound.
    d = simulate_stopping_trials(4000, 0.15, 0.3, 0.4, 0.15, guess_rate=0.02, ndt_probs=NDT_PROBS,
                                 rng=np.random.default_rng(6))
    assert d["wall_hit"].mean() > 0.2
    r = fit_stopping_model(d, group_col=None)
    assert abs(r["params"]["bound_mean"].iloc[0] - 0.4) < 0.04


def test_groups_without_post_data_report_nan_post():
    d = pd.concat([_sim(500, 0.01, 7).assign(block_index=1),
                   _sim(500, 0.01, 8, change_point=6, generative_mean_post=0.03).assign(block_index=3)],
                  ignore_index=True)
    p = fit_stopping_model(d, post_params=("bound_mean",))["params"].set_index("group")
    assert np.isnan(p.loc[1, "bound_mean_post"]) and np.isfinite(p.loc[3, "bound_mean_post"])


def test_fit_rejects_missing_choices():
    d = _sim(50, 0.02, 9)
    d.loc[0, "choice"] = np.nan
    with pytest.raises(ValueError, match="missing choice"):
        fit_stopping_model(d, group_col=None)
