"""
Data loading and the direct (per-trial) bound measure.

Python translations of the MATLAB getPigeon_* functions (see each function's
docstring for its source).

Main pipeline
-------------
1. ``get_data_table`` — reads each subject's CSV file (one folder per task:
   OL, MX, PD, MXSC), calls ``get_bounds`` on the step sequences, optionally
   relabels the six blocks of OL/MX/PD as three conditions, and, if asked,
   applies ``apply_bias_corrections``.
2. ``get_bounds`` — from the step sequences infers each trial's bound (the
   position at the inferred commit step), DT (steps after the NDT), RT (total
   steps), the congruence curve used to estimate the NDT, and RT cutoffs.
3. ``get_good_trial_array`` — the standard trial filter: DT ≥ 2,
   trial_number ≥ 10, no wall hit, RT at or above the cutoff.
4. ``apply_bias_corrections`` — corrects the measured bound for overshoot by
   inverting a simulated calibration table
   (``notebooks/archive/Make_biasCorrection.ipynb``). Off by default: the
   figures use raw bounds.
5. ``get_bound_summary`` / ``get_performance_summary`` — per subject, block
   and SNR summaries of |bound|, accuracy and DT.

Also: ``get_crossing_diagnostics`` and ``get_steps_before_decision`` (features
of the steps around the inferred commit, compared with the stopping model in
the Figure 3 supplements), ``get_bounds_from_dv`` (``get_bounds`` for a
simulated position matrix, used by the bias calibration), and
``get_cp_generative_params`` / ``check_calibration_snrs`` (the change-point
task's step statistics, read from the data, and a check that a calibration
covers the data's SNRs).

Key constants
-------------
WALL : float
    Screen-edge limit (0.75). Trials where any position reaches it are
    flagged ``wall_hit`` and excluded by ``get_good_trial_array``.
"""

from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd
import scipy.io

from .pathDefaults import RAW_DATA_DIR

WALL = 0.75  # screen-edge limit; trials where any step position reaches |WALL| are flagged wall_hit = True


def get_data_table(
    task_type="MX",
    data_dir=RAW_DATA_DIR,
    blocks="all",
    combine_snr=True,
    correct_bias=None,
    max_ndt=5,
    peak_step_bound=True,
):
    """
    Load and return a DataFrame of trial data.
    Translated from getPigeon_dataTable.m

    Parameters
    ----------
    task_type : str
        'OL' (blocked SNR, cohort 1), 'MX' (mixed SNR, cohort 2), 'PD'
        (predefined bound), or 'MXSC' (change-point task). Reads
        ``data_dir/<task_type>/*.csv``.

        - 'OL', 'MX' and 'MXSC' are online tasks: the bound, DT and RT are
          inferred from the step sequences by ``get_bounds``.
        - 'PD': the subject chooses the bound before the trial starts, so the
          bound is ``predefined_bound`` signed by the choice (right = +), DT =
          RT (no NDT to subtract), and no bias correction is applied.
        - 'MXSC': blocks 1/2 are the fixed low-/high-SNR blocks, 3/4 the
          LowHigh/HighLow change-point blocks. ``change_point`` is the step at
          which the SNR switched, read from the task's ``switch_time`` column
          (0 outside blocks 3/4). A session abandoned before block 3 has no
          ``switch_time`` column; its ``change_point`` is all 0.
    data_dir : str or Path
        Top-level raw-data directory.
    blocks : 'all' or list of int
        Raw block numbers to load.
    combine_snr : bool
        OL/MX/PD only: relabel the six blocks as three conditions. If block 1
        has a single SNR (OL, PD: blocks 4-6 repeat the conditions of 1-3 at
        high SNR), blocks 4-6 become 1-3; otherwise (MX: blocks 1-3 mix the
        two SNRs) blocks 4-6 are dropped.
    correct_bias : str, Path or None
        Bias-correction calibration file for ``apply_bias_corrections``
        (``pathDefaults.BIAS_CORRECTION_FILE``, or ``BIAS_CORRECTION_CP_FILE``
        for 'MXSC'), or None (default) for raw bounds. A missing file raises.
        Ignored for 'PD' (the bound is set, not measured). For 'MXSC' the file
        must cover the data's SNRs (checked).
    max_ndt : int
        Max NDT lag for the bound matrix (see get_bounds).
    peak_step_bound : bool
        Apply get_bounds' peak-step correction (default True).

    Returns
    -------
    pd.DataFrame with columns:
        subject_index, block_index, trial_number, bound, abs_bound, RT, DT,
        change_point, choice, correct, coin_count, snr, step_std, steps,
        congruence, rt_cutoff, rt_below_cutoff, wall_hit
    """
    is_online = task_type in ("OL", "MX", "MXSC")
    is_cp = task_type == "MXSC"

    files = sorted(glob.glob(os.path.join(data_dir, task_type, "*.csv")))
    all_tables = []

    for subject_index, fpath in enumerate(files, start=1):
        raw = pd.read_csv(fpath, encoding="utf-8-sig")

        lg = raw["trial_number"].notna()
        if isinstance(blocks, list):
            lg = lg & raw["block_number"].isin(blocks)

        if task_type == "PD":
            # PD CSVs interleave trial-metadata rows (trial_number present) with
            # pigeon-data rows (trial_number absent). Access next_rows from the
            # raw DataFrame before filtering so the i+1 index is always valid.
            # step_mean_val/step_std_val (for SNR) live on the metadata row
            # alongside predefined_bound/correct, not on the data row.
            orig_idx = raw.index[lg].tolist()
            orig_idx = [i for i in orig_idx if i + 1 < len(raw)]  # drop if no following row
            trial_rows = raw.loc[orig_idx].reset_index(drop=True)
            next_rows = raw.loc[[i + 1 for i in orig_idx]].reset_index(drop=True)
            tmp = pd.concat(
                [
                    trial_rows[
                        ["block_number", "trial_number", "predefined_bound", "correct", "step_mean_val", "step_std_val"]
                    ],
                    next_rows[["pigeon_steps", "choice", "coins_count"]],
                ],
                axis=1,
            )
        else:
            cols = [
                "block_number",
                "trial_number",
                "pigeon_steps",
                "choice",
                "correct",
                "steps_count",
                "step_mean_val",
                "step_std_val",
                "coins_count",
            ]
            if is_cp and "switch_time" in raw.columns:
                cols.append("switch_time")
            tmp = raw.loc[lg, cols].reset_index(drop=True)

        n_trials = len(tmp)
        rows = {
            "subject_index": np.full(n_trials, subject_index),
            "block_index": tmp["block_number"].to_numpy(dtype=float),
            "trial_number": tmp["trial_number"].to_numpy(dtype=float),
            "bound": np.full(n_trials, np.nan),
            "abs_bound": np.full(n_trials, np.nan),
            "RT": np.full(n_trials, np.nan),
            "DT": np.full(n_trials, np.nan),
            "change_point": np.zeros(n_trials),
            "choice": np.full(n_trials, np.nan),
            "correct": np.full(n_trials, np.nan),
            # PD's coins_count column occasionally holds a block-end bonus
            # message ("No bonus" / "Bonus!") instead of a running total --
            # a PsychoPy logging quirk that overwrites the last trial of each
            # block. coerce=NaN rather than crashing; coin_count isn't used by
            # any bound/DT analysis.
            "coin_count": pd.to_numeric(tmp["coins_count"], errors="coerce").to_numpy(dtype=float),
            "snr": (tmp["step_mean_val"] / tmp["step_std_val"]).to_numpy(dtype=float),
            # Per-step noise SD; with snr this recovers the generative mean
            # (|snr| * step_std) that simulations of the task use.
            "step_std": tmp["step_std_val"].abs().to_numpy(dtype=float),
            "steps": [None] * n_trials,
            "congruence": [None] * n_trials,
            "rt_cutoff": np.ones(n_trials),
        }

        # Parse steps and choices per trial
        for tt in range(n_trials):
            steps_str = tmp["pigeon_steps"].iloc[tt]
            if isinstance(steps_str, str):
                steps = np.array([float(x) for x in steps_str.strip("[]").split(",") if x.strip()], dtype=float)
            else:
                steps = np.array([], dtype=float)
            rows["steps"][tt] = steps

            choice_val = tmp["choice"].iloc[tt]
            if isinstance(choice_val, str) and choice_val in ("right", "left"):
                rows["choice"][tt] = 1.0 if choice_val == "right" else 0.0
                correct_val = tmp["correct"].iloc[tt]
                if isinstance(correct_val, str):
                    rows["correct"][tt] = 1.0 if choice_val == correct_val else 0.0
            elif isinstance(choice_val, (int, float)) and np.isfinite(choice_val):
                rows["choice"][tt] = float(choice_val)
                rows["correct"][tt] = float(tmp["correct"].iloc[tt])

            if task_type == "PD":
                rows["RT"][tt] = len(steps)
                # The bound is chosen before the trial starts; sign it by the
                # choice (right = +, as get_bounds' position-based sign). Left
                # NaN if the choice wasn't parsed.
                if np.isfinite(rows["choice"][tt]):
                    sign = 1.0 if rows["choice"][tt] == 1.0 else -1.0
                    rows["bound"][tt] = sign * float(tmp["predefined_bound"].iloc[tt])

        if is_cp:
            l_cp_block = np.isin(rows["block_index"], [3, 4])
            if "switch_time" in tmp.columns:
                # The task records the switch step on every trial of the change-point blocks.
                switch_time = pd.to_numeric(tmp["switch_time"], errors="coerce").to_numpy(dtype=float)
                rows["change_point"] = np.where(l_cp_block, switch_time, 0.0)
            elif l_cp_block.any():
                raise ValueError(
                    f"{os.path.basename(fpath)} has change-point blocks but no switch_time "
                    "column (a task version this loader does not support)."
                )

        if is_online:
            bounds, dts, rts, congruence, rt_cutoffs = get_bounds(
                rows["steps"],
                rows["choice"],
                snr=np.abs(rows["snr"]),
                block_ids=rows["block_index"],
                ndt=None,
                max_ndt=max_ndt,
                peak_step_bound=peak_step_bound,
            )
            rows["bound"] = bounds
            rows["DT"] = dts
            rows["RT"] = rts
            rows["congruence"] = [congruence] * n_trials
            rows["rt_cutoff"] = rt_cutoffs
        elif task_type == "PD":
            rows["DT"] = rows["RT"].copy()  # no NDT: every step is deliberation time

        rows["abs_bound"] = np.abs(rows["bound"])
        all_tables.append(pd.DataFrame(rows))

    data_table = pd.concat(all_tables, ignore_index=True)

    # Flag trials below the per-(subject, block, SNR) RT reliability cutoff.
    data_table["rt_below_cutoff"] = data_table["RT"] < data_table["rt_cutoff"]

    # Mark trials where the pigeon reached the screen edge (|step| >= WALL).
    # On these trials the step logger kept recording after the wall was hit,
    # inflating RT and DT. The wall-hit step itself is the true end of the trial.
    data_table["wall_hit"] = data_table["steps"].apply(
        lambda s: s is not None and len(s) > 0 and bool(np.any(np.abs(s[np.isfinite(s)]) >= WALL - 1e-9))
    )

    # Relabel six blocks as three conditions (never for MXSC, whose four blocks are distinct conditions).
    if (
        combine_snr
        and not is_cp
        and sorted(data_table["block_index"].dropna().unique().astype(int)) == list(range(1, 7))
    ):
        block1_snrs = data_table.loc[data_table["block_index"] == 1, "snr"].dropna()
        if len(block1_snrs.abs().unique()) == 1:
            # blocked: remap blocks 4-6 -> 1-3
            for b in range(1, 4):
                data_table.loc[data_table["block_index"] == b + 3, "block_index"] = b
        else:
            # mixed: drop blocks 4-6
            data_table = data_table[data_table["block_index"] <= 3].reset_index(drop=True)

    if correct_bias and task_type != "PD":
        if not os.path.exists(correct_bias):
            raise FileNotFoundError(f"bias-correction file not found: {correct_bias}")
        if is_cp:
            # The CP task's SNRs are fixed by its design, so its calibration must have been simulated at
            # exactly those SNRs.
            calib = scipy.io.loadmat(correct_bias, squeeze_me=True)
            check_calibration_snrs(calib["snrs"], data_table, source=correct_bias)
        data_table = apply_bias_corrections(data_table, correct_bias)

    return data_table


def _compute_rt_cutoff(bound_matrix, choices_pm, rts, threshold=0.65, min_trials=5):
    """
    Find the minimum RT cutoff C such that trials with RT >= C have
    max congruence (across NDT lags) >= threshold.

    Iterates from the largest RT down to the smallest. At each candidate
    cutoff r, computes max_k(congruence) for all trials with RT >= r.
    Returns the smallest r for which this still meets the threshold.

    Parameters
    ----------
    bound_matrix : (n_trials, max_ndt) array
    choices_pm   : (n_trials,) array  —  choices coded as ±1
    rts          : (n_trials,) array  —  response times
    threshold    : float              —  congruence threshold (default 0.65)
    min_trials   : int                —  minimum trials per RT bin to compute congruence

    Returns
    -------
    int : minimum RT to include (exclude trials with RT < cutoff).
          Returns 1 if all RTs meet the threshold (no cutoff needed).
    """
    max_ndt = bound_matrix.shape[1]
    rt_vals = sorted(np.unique(rts[np.isfinite(rts)].astype(int)))
    cutoff = 1  # default: no cutoff needed

    for r in reversed(rt_vals):
        mask = np.isfinite(rts) & (rts.astype(int) >= r)
        if mask.sum() < min_trials:
            continue
        max_cong = 0.0
        for k in range(max_ndt):
            lc = mask & (bound_matrix[:, k] != 0)
            if lc.sum() >= min_trials:
                cong = np.mean(np.sign(bound_matrix[lc, k]) == choices_pm[lc])
                max_cong = max(max_cong, cong)
        if max_cong >= threshold:
            cutoff = r  # threshold met; try including one shorter RT
        else:
            break  # adding shorter RT drops below threshold; stop

    return cutoff


def get_bounds(
    steps_list,
    choices,
    min_rt=1,
    snr=None,
    block_ids=None,
    rt_cutoff_threshold=0.65,
    ndt=2,
    max_ndt=5,
    peak_step_bound=True,
):
    """
    Compute bounds, decision times, response times, and congruences.
    Translated from getPigeon_bounds.m

    Parameters
    ----------
    steps_list : list of np.ndarray
    choices : array-like of float (0/1)
    min_rt : int
    snr : array-like or None
        Per-trial |SNR|. Used only to pick out the lowest-SNR condition for
        NDT estimation when `ndt=None` (see below) -- has no other effect.
        One call to `get_bounds` is assumed to cover a single subject's
        trials (this is how `get_data_table` calls it); passing pooled
        multi-subject data would estimate one NDT for the whole pool.
    block_ids : array-like or None
        Block identifier per trial. If provided, the RT cutoff is computed
        separately for each (block, SNR) combination. If None, a single
        cutoff is computed across all trials.
    rt_cutoff_threshold : float
        Congruence threshold for the RT cutoff (default 0.65). Set to None
        to skip cutoff computation (rt_cutoffs returned as all-ones).
    ndt : int or None
        NDT lag to use for bound extraction. If an integer, all trials use
        this fixed lag (clipped to RT-2). If None, a single NDT lag is
        estimated for all trials in this call -- see "NDT estimation" below.
    max_ndt : int
        Max NDT lag considered when building the bound matrix (default 5;
        must be >= 4 to support the [1, 3] NDT search below).
    peak_step_bound : bool
        If True (default), apply the peak-step bound correction: for trials
        where the pigeon is moving away from the choice side at the NDT
        crossing, replace the midpoint bound with steps[RT-2-ndt] — the
        earlier, outermost of the two crossing steps (furthest from centre).
        This is a Python-only addition not present in getPigeon_bounds.m at
        all; applied uniformly to every task type (MX/OL/PD/MXSC).

    NDT estimation (when ndt=None)
    -------------------------------
    A single NDT lag is estimated from this call's lowest-|SNR| trials only
    (not pooled across SNR, not estimated separately per SNR group), then
    applied to every trial regardless of its own SNR. Lower SNR means the
    pigeon's position more often drifts backward after the true bound
    crossing, which is what lets the congruence-vs-lag curve sharply
    localize the true crossing lag; at higher SNR the position rarely
    reverses, so the curve stays flat across several lags and doesn't
    cleanly identify one -- pooling across SNR, or estimating separately per
    SNR group, both end up letting that flat, uninformative high-SNR curve
    pull the estimate toward lags that aren't really about NDT (confirmed on
    real MX/OL data: pooled and per-SNR-group estimates disagreed for
    17-23% of subjects, consistently toward higher lags for the per-SNR
    high-SNR estimate). The search itself is restricted to lags 1-3: NDT=0
    (zero motor delay) and NDT>=4 aren't physiologically plausible, so an
    unrestricted argmax landing there almost certainly reflects estimation
    noise rather than a real value; restricting the search (rather than
    clamping an out-of-range answer) picks the best still-plausible lag
    instead. Ties broken toward the largest lag. See notebooks/Test_NDT.ipynb
    for the analysis behind this.

    Returns
    -------
    bounds : np.ndarray
    dts : np.ndarray
    rts : np.ndarray
    congruences : np.ndarray, shape (max_ndt, n_snrs)
        Per-SNR-group congruence, for diagnostics only -- NDT estimation
        itself only uses the lowest-SNR column, and only lags 1-3 of it.
    rt_cutoffs : np.ndarray, shape (n_trials,)
        Per-trial RT cutoff. Trials with RT < rt_cutoffs[i] are below the
        reliability threshold and should be excluded from bound analyses.
    """
    n_trials = len(steps_list)
    choices_pm = np.array(choices) * 2 - 1  # convert 0/1 to -1/+1

    if snr is None:
        snr = np.zeros(n_trials)
    snr = np.asarray(snr)
    unique_snrs = np.unique(snr[np.isfinite(snr)])
    n_snrs = len(unique_snrs)

    if block_ids is None:
        block_ids = np.zeros(n_trials)
    block_ids = np.asarray(block_ids)

    # Build the bound matrix.
    # For each trial, take the last min(RT, max_ndt) step positions, reverse them,
    # and compute midpoints between consecutive pairs.  The midpoint at lag k is:
    #   bound_matrix[i, k] = (steps[RT-1-k] + steps[RT-2-k]) / 2
    # This estimates where the accumulator was when the decision threshold was crossed
    # at NDT lag k steps before the response.
    bound_matrix = np.zeros((n_trials, max_ndt))
    rts = np.full(n_trials, np.nan)

    for ii in range(n_trials):
        these_steps = steps_list[ii]
        these_steps = these_steps[np.isfinite(these_steps)] if these_steps is not None else np.array([])
        rts[ii] = len(these_steps)

        # MATLAB's steps{ii}(max(rts-maxNDT,1):end) is a 1-indexed, inclusive
        # slice of length maxNDT+1 (when rts>maxNDT); the equivalent 0-indexed
        # start is max(rts-maxNDT,1)-1 = max(rts-maxNDT-1,0), not max(rts-maxNDT,0)
        # (that under-counts by one element and silently drops the deepest NDT lag).
        final_steps = these_steps[max(int(rts[ii]) - max_ndt - 1, 0) :][::-1]  # reversed
        if len(final_steps) > 1:
            # midpoints between consecutive pairs
            midpoints = final_steps[1:] - np.diff(final_steps) / 2
            bound_matrix[ii, : len(midpoints)] = midpoints

    # Per-SNR-group congruence, for diagnostics only (see docstring).
    # Congruence at lag k = fraction of trials where sign(bound_matrix[:, k])
    # matches the choice direction (+1 = right, -1 = left).
    ndts = np.full(n_trials, np.nan)
    bounds = np.full(n_trials, np.nan)
    congruences = np.full((max_ndt, n_snrs), np.nan)

    for ss, snr_val in enumerate(unique_snrs):
        ls = np.isclose(snr, snr_val)
        for ii in range(max_ndt):
            lc = ls & (bound_matrix[:, ii] != 0)
            if lc.sum() > 5:
                congruences[ii, ss] = np.sum(np.sign(bound_matrix[lc, ii]) == choices_pm[lc]) / lc.sum()

    if ndt is not None:
        # Fixed NDT lag, same for every trial (used by calibration/simulation
        # callers that already know the ground-truth NDT).
        ndts[:] = np.clip(rts - 2, 0, int(ndt))
    else:
        # Estimate a single NDT lag from the lowest-|SNR| trials only, search
        # restricted to lags 1-3, then apply it to every trial in this call
        # regardless of SNR -- see "NDT estimation" in the docstring.
        low_snr_val = unique_snrs.min() if n_snrs > 0 else 0.0
        ls = np.isclose(snr, low_snr_val)
        low_snr_cong = np.full(max_ndt, np.nan)
        for ii in range(1, min(4, max_ndt)):
            lc = ls & (bound_matrix[:, ii] != 0)
            if lc.sum() > 5:
                low_snr_cong[ii] = np.sum(np.sign(bound_matrix[lc, ii]) == choices_pm[lc]) / lc.sum()
        if np.any(np.isfinite(low_snr_cong)):
            max_cong = np.nanmax(low_snr_cong)
            ci = int(np.where(low_snr_cong == max_cong)[0][-1])  # ties -> largest lag
            ndts[:] = np.clip(rts - 2, 0, ci)

    # Extract bound for each trial from its NDT lag.
    # With peak_step_bound=True: for trials where the pigeon is moving away from
    # the choice side at the NDT crossing, replace the midpoint with steps[RT-2-k]
    # (the earlier, outermost step — furthest from centre when retreating).
    for tt in np.where(np.isfinite(ndts))[0]:
        k = int(ndts[tt])
        mid = bound_matrix[tt, k]

        if peak_step_bound and mid != 0:
            sc = steps_list[tt]
            sc = sc[np.isfinite(sc)] if sc is not None else np.array([])
            RT = int(rts[tt])
            t_later = RT - 1 - k  # later step (closer to response)
            t_earlier = RT - 2 - k  # earlier step (furthest from centre when retreating)
            if 0 <= t_earlier < len(sc) and t_later < len(sc):
                step_in = sc[t_later] - sc[t_earlier]
                if step_in * np.sign(mid) < 0:  # backward motion at crossing
                    bounds[tt] = sc[t_earlier]
                    continue

        bounds[tt] = mid

    # Remove bounds from very short trials
    bounds[rts < min_rt] = np.nan

    # DT = steps after the NDT period ends (i.e. the "deliberation time")
    dts = np.maximum(0, rts - ndts - 1)

    # Compute RT cutoff per (block, SNR) group.
    # For each group, find the minimum RT such that trials with RT >= that value
    # have max congruence (across NDT lags) >= rt_cutoff_threshold.
    rt_cutoffs = np.ones(n_trials, dtype=float)
    if rt_cutoff_threshold is not None:
        for blk in np.unique(block_ids[np.isfinite(block_ids.astype(float))]):
            for snr_val in unique_snrs:
                group = np.isclose(block_ids.astype(float), float(blk)) & np.isclose(snr, snr_val)
                if group.sum() < 5:
                    continue
                cutoff = _compute_rt_cutoff(
                    bound_matrix[group],
                    choices_pm[group],
                    rts[group],
                    threshold=rt_cutoff_threshold,
                )
                rt_cutoffs[group] = cutoff

    return bounds, dts, rts, congruences, rt_cutoffs


def get_bounds_from_dv(choices, rts, DV, max_ndt=5, rt_cutoff_threshold=0.65, ndt=2, peak_step_bound=True):
    """
    Like get_bounds but takes a pre-built DV matrix instead of a steps list.

    Intended for vectorised use with simulation output (e.g. bias-correction
    calibration) where DV is already a 2-D numpy array.  The bound logic —
    midpoint construction, NDT selection, peak-step correction, RT cutoff — is
    identical to get_bounds.

    Parameters
    ----------
    choices : (n,) array-like  0 = left, 1 = right
    rts     : (n,) array-like  number of steps taken per trial
    DV      : (n, max_steps) float array  DV[i, t] = pigeon position at step t
    max_ndt : int
    rt_cutoff_threshold : float or None
    ndt     : int or None  fixed NDT lag; None -> pick by max congruence
    peak_step_bound : bool  see get_bounds

    Returns
    -------
    bounds, dts, rts, congruence, rt_cutoffs
        Same semantics as get_bounds; congruence has shape (max_ndt,) with
        no SNR dimension (caller supplies one SNR group at a time).
    """
    n_trials = len(choices)
    rts = np.asarray(rts, dtype=float)
    choices_pm = np.asarray(choices, dtype=float) * 2 - 1

    # ── Build bound matrix (vectorised) ──────────────────────────────────────
    # bound_matrix[i, k] = (DV[i, RT-1-k] + DV[i, RT-2-k]) / 2
    bound_matrix = np.zeros((n_trials, max_ndt))
    for k in range(max_ndt):
        rows = np.where(rts >= k + 2)[0]
        if len(rows):
            r = rts[rows].astype(int)
            bound_matrix[rows, k] = (DV[rows, r - 1 - k] + DV[rows, r - 2 - k]) / 2

    # ── NDT selection ────────────────────────────────────────────────────────
    congruence = np.full(max_ndt, np.nan)
    for k in range(max_ndt):
        lc = bound_matrix[:, k] != 0
        if lc.sum() > 5:
            congruence[k] = np.mean(np.sign(bound_matrix[lc, k]) == choices_pm[lc])

    ndts = np.full(n_trials, np.nan)
    if ndt is not None:
        ndts[:] = np.clip(rts - 2, 0, int(ndt))
    else:
        if np.any(np.isfinite(congruence)):
            max_cong = np.nanmax(congruence)
            ci = int(np.where(congruence == max_cong)[0][-1])
            ndts[:] = np.clip(rts - 2, 0, ci)

    # ── RT cutoff ────────────────────────────────────────────────────────────
    rt_cutoffs = np.ones(n_trials, dtype=float)
    if rt_cutoff_threshold is not None:
        rt_cutoffs[:] = _compute_rt_cutoff(bound_matrix, choices_pm, rts, threshold=rt_cutoff_threshold)

    # ── Extract bounds with peak-step correction ──────────────────────────────
    bounds = np.full(n_trials, np.nan)
    for tt in np.where(np.isfinite(ndts))[0]:
        k = int(ndts[tt])
        mid = bound_matrix[tt, k]

        if peak_step_bound and mid != 0:
            RT = int(rts[tt])
            t_later = RT - 1 - k
            t_earlier = RT - 2 - k
            if 0 <= t_earlier < DV.shape[1] and t_later < DV.shape[1]:
                step_in = DV[tt, t_later] - DV[tt, t_earlier]
                if step_in * np.sign(mid) < 0:
                    bounds[tt] = DV[tt, t_earlier]
                    continue
        bounds[tt] = mid

    # ── DTs ──────────────────────────────────────────────────────────────────
    dts = np.maximum(0, rts - ndts - 1)

    return bounds, dts, rts, congruence, rt_cutoffs


def get_crossing_diagnostics(data_table):
    """
    Per-trial incongruence and premature-crossing flags at the inferred crossing.

    Used by Figure03S03_suboptimalBehavior, which asks whether the stopping
    model reproduces them:

    - **incongruent**: the sign of the basic midpoint bound
      ``(steps[DT-1] + steps[DT]) / 2`` differs from the choice.
    - **premature crossing**: some position before ``DT - 1`` was already at or
      beyond the peak-step bound ``max(|steps[DT-1]|, |midpoint|)`` on the
      bound's side.

    Parameters
    ----------
    data_table : pd.DataFrame
        ``steps``, ``choice`` (0/1), ``DT`` and ``bound`` columns.

    Returns
    -------
    pd.DataFrame with columns ``incongruent`` and ``premature_crossing`` (1.0 /
    0.0, NaN where undefined: DT < 1, DT beyond the recorded steps, or a zero
    midpoint), same index as data_table.
    """
    choices_pm = 2 * data_table["choice"].to_numpy(float) - 1
    dts = data_table["DT"].to_numpy(float)
    bounds = data_table["bound"].to_numpy(float)
    incong = np.full(len(data_table), np.nan)
    early = np.full(len(data_table), np.nan)
    for ii, sc in enumerate(data_table["steps"]):
        if sc is None or not np.isfinite(dts[ii]):
            continue
        sc = np.asarray(sc, float)
        t = int(dts[ii])
        if t < 1 or t >= len(sc) or not np.isfinite(sc[t]) or not np.isfinite(sc[t - 1]):
            continue
        midpoint = (sc[t - 1] + sc[t]) / 2
        if midpoint == 0:
            continue
        incong[ii] = float(np.sign(midpoint) != choices_pm[ii])
        peak_b = max(abs(sc[t - 1]), abs(midpoint))
        if peak_b <= 0:
            continue
        sgn = np.sign(bounds[ii]) if np.isfinite(bounds[ii]) and bounds[ii] != 0 else np.sign(midpoint)
        early[ii] = float(np.any(sc[: t - 1] * sgn >= peak_b)) if t >= 2 else 0.0
    return pd.DataFrame({"incongruent": incong, "premature_crossing": early}, index=data_table.index)


def get_steps_before_decision(data_table, num_steps=2):
    """
    Signed sizes of the last steps before the decision, toward the choice.

    ``step_0`` is the step into the decision position, ``steps[DT] -
    steps[DT-1]`` (the step whose midpoint is the basic bound estimate);
    ``step_1`` is the step before it, ``steps[DT-1] - steps[DT-2]``; and so on.
    Each is multiplied by the choice sign (+1 right, -1 left), so positive
    values move toward the side chosen.

    Parameters
    ----------
    data_table : pd.DataFrame
        ``steps`` (cumulative positions, ``steps[0]`` = start), ``choice`` (0/1)
        and ``DT`` columns.
    num_steps : int
        Number of steps back from the decision to return.

    Returns
    -------
    pd.DataFrame with columns ``step_0`` ... ``step_{num_steps-1}``, same index
    as data_table; NaN where the step does not exist (DT too small, DT beyond
    the recorded steps, or a non-finite DT).
    """
    choices_pm = 2 * data_table["choice"].to_numpy(float) - 1
    dts = data_table["DT"].to_numpy(float)
    out = np.full((len(data_table), num_steps), np.nan)
    for ii, sc in enumerate(data_table["steps"]):
        if sc is None or not np.isfinite(dts[ii]):
            continue
        sc = np.asarray(sc, float)
        t = int(dts[ii])
        for kk in range(num_steps):
            if t - kk - 1 >= 0 and t - kk < len(sc):
                out[ii, kk] = (sc[t - kk] - sc[t - kk - 1]) * choices_pm[ii]
    return pd.DataFrame(out, columns=[f"step_{kk}" for kk in range(num_steps)], index=data_table.index)


def get_good_trial_array(data_table, min_dt=2, min_trial_number=10, block_index=None, apply_rt_cutoff=True):
    """
    Standard trial selection filter.
    Translated from getPigeon_goodTrialArray.m

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table (or get_simulated_data_table).
    min_dt : int or None
        Minimum DT (decision time, steps). Excludes trials too short to
        estimate a reliable bound. Default 2.
    min_trial_number : int or None
        Minimum trial number within a block. Excludes early warm-up trials
        where participants are still learning the task. Default 10.
    block_index : int, list, or None
        If given, keep only trials from the specified block(s).
    apply_rt_cutoff : bool
        If True and 'rt_below_cutoff' column is present, excludes trials
        below the per-(block, SNR) RT reliability cutoff computed in
        get_bounds. Default True.

    Returns
    -------
    pd.Series of bool, same index as data_table.
        True for trials that pass all filters (i.e. should be included
        in bound and performance analyses).
    """
    lg = pd.Series(True, index=data_table.index)

    if min_dt is not None:
        lg = lg & (data_table["DT"] >= min_dt)
    if min_trial_number is not None:
        lg = lg & (data_table["trial_number"] >= min_trial_number)
    if block_index is not None:
        lg = lg & data_table["block_index"].isin([block_index] if np.isscalar(block_index) else block_index)
    # Exclude wall-hit trials: pigeon reached screen edge, inflating RT/DT
    if "wall_hit" in data_table.columns:
        lg = lg & ~data_table["wall_hit"]
    # Exclude trials below the per-(subject, block, SNR) RT reliability cutoff
    if apply_rt_cutoff and "rt_below_cutoff" in data_table.columns:
        lg = lg & ~data_table["rt_below_cutoff"]

    return lg


def apply_bias_corrections(data_table, bias_file):
    """
    Correct measured bounds for the estimator's bias, from a simulated calibration table.

    The calibration file (``notebooks/archive/Make_biasCorrection.ipynb``) holds the
    mean *measured* |bound| for each combination of true bound, DT bin and SNR
    bin (``boundSummary[true bound, DT - 1, SNR bin]``, true bounds
    ``simBounds``). The correction inverts this curve: given a measured bound
    M at a DT and SNR, ``np.interp`` returns the true bound T whose mean
    measured bound is M (so the nonlinearity at small bounds, where a single
    step can overshoot the bound, is followed). Measured bounds beyond the
    calibrated range are extrapolated linearly from the curve's edge slope
    rather than clamped (short-DT bins often have no calibration points at large
    true bounds, which rarely end in few steps). Corrected bounds are floored at
    0.005. The last DT bin is open-ended (DT >= n_dt_bins).

    SNR bins: ``snrBinEdges`` (N edges -> N + 1 bins; bin i is
    ``edges[i-1] <= |snr| < edges[i]``). Trials with non-finite |snr| are left
    uncorrected.

    Parameters
    ----------
    data_table : pd.DataFrame
        Must contain 'bound', 'DT' and 'snr' columns.
    bias_file : str or Path
        Calibration .mat file with ``boundSummary``, ``simBounds`` and ``snrBinEdges``.

    Returns
    -------
    pd.DataFrame
        Copy of data_table with 'bound' and 'abs_bound' replaced by their
        bias-corrected values.
    """
    mat = scipy.io.loadmat(bias_file)
    bound_summary = mat["boundSummary"]  # (n_bounds, n_dt_bins, n_snr_bins)
    sim_bounds = mat["simBounds"].ravel()  # (n_bounds,)
    edges = np.asarray(mat["snrBinEdges"]).ravel()
    n_dts = bound_summary.shape[1]

    snrs = np.abs(data_table["snr"].to_numpy())
    snr_bin = np.where(np.isfinite(snrs), np.digitize(snrs, edges), -1)  # bin i: edges[i-1] <= snr < edges[i]
    dts = data_table["DT"].to_numpy()
    bounds = data_table["bound"].to_numpy(dtype=float).copy()

    for dd in range(n_dts):
        ld = (dts == dd + 1) if dd < n_dts - 1 else (dts >= dd + 1)
        for mm in range(len(edges) + 1):
            ls = ld & (snr_bin == mm)
            if not ls.any():
                continue
            x = bound_summary[:, dd, mm]  # mean measured bound at each true bound
            lvalid = np.isfinite(x)
            if lvalid.sum() < 2:
                continue
            order = np.argsort(x[lvalid])  # a monotone interpolation grid
            corrected = np.maximum(
                0.005, _interp_with_extrapolation(np.abs(bounds[ls]), x[lvalid][order], sim_bounds[lvalid][order])
            )
            bounds[ls] = np.sign(bounds[ls]) * corrected

    data_table = data_table.copy()
    data_table["bound"] = bounds
    data_table["abs_bound"] = np.abs(bounds)
    return data_table


def _interp_with_extrapolation(x, xv, yv):
    """
    Like ``np.interp``, but linearly extrapolates past the edges of
    ``(xv, yv)`` instead of clamping to the boundary value. ``xv`` must be
    sorted ascending with at least 2 points.
    """
    x = np.asarray(x, dtype=float)
    y = np.interp(x, xv, yv)
    below = x < xv[0]
    above = x > xv[-1]
    if below.any():
        slope = (yv[1] - yv[0]) / (xv[1] - xv[0])
        y[below] = yv[0] + slope * (x[below] - xv[0])
    if above.any():
        slope = (yv[-1] - yv[-2]) / (xv[-1] - xv[-2])
        y[above] = yv[-1] + slope * (x[above] - xv[-1])
    return y


def get_performance_summary(data_table, blocks="all", snrs="all"):
    """
    Compute per-subject/block/SNR accuracy and DT stats.
    Translated from getPigeon_performanceSummary.m

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table.
    blocks : 'all' or array-like of int
        'all' uses blocks 1-3; otherwise only the given block(s), in the
        given order.
    snrs : 'all' or array-like of float
        'all' uses every unique |snr| value present in data_table;
        otherwise only the given |snr| value(s), in the given order.

    Returns
    -------
    np.ndarray, shape (n_subjects, n_blocks, n_snrs, 4)
        Last dim: [accuracy, mean_DT, std_DT, n_trials]
    """
    subject_indices = np.sort(data_table["subject_index"].dropna().unique())
    n_subjects = len(subject_indices)

    block_indices = np.arange(1, 4) if blocks == "all" else np.atleast_1d(np.asarray(blocks))
    n_blocks = len(block_indices)

    abs_snr = np.abs(data_table["snr"].to_numpy())
    if snrs == "all":
        abs_snrs = np.sort(np.unique(abs_snr[np.isfinite(abs_snr)]))
    else:
        abs_snrs = np.asarray(snrs)
    n_snrs = len(abs_snrs)

    lg = get_good_trial_array(data_table)

    summary = np.zeros((n_subjects, n_blocks, n_snrs, 4))

    for si, subj in enumerate(subject_indices):
        ls = lg & (data_table["subject_index"] == subj)

        for bi, block in enumerate(block_indices):
            lsb = ls & (data_table["block_index"] == block)

            for ni, snr_val in enumerate(abs_snrs):
                lsnr = lsb & np.isclose(abs_snr, snr_val)
                if lsnr.any():
                    subset = data_table[lsnr]
                    summary[si, bi, ni] = [
                        subset["correct"].sum() / len(subset),
                        subset["DT"].mean(),
                        subset["DT"].std(),
                        len(subset),
                    ]
                else:
                    summary[si, bi, ni] = [np.nan, np.nan, np.nan, 0]

    return summary


def get_bound_summary(
    data_table, correct_only=False, blocks="all", split_by_snr=True, max_rt=10, apply_quality_filter=True
):
    """
    Summarize |bound| by subject, block, SNR, and DT.
    Translated from getPigeon_boundSummary.m

    Parameters
    ----------
    data_table : pd.DataFrame
        Output of get_data_table.
    correct_only : bool
        If True, restrict to correct trials only. Default False (all
        trials with a finite choice, i.e. correct in {0, 1}).
    blocks : 'all' or list/scalar of block numbers
        'all' uses every block present in data_table; otherwise only the
        given block(s) are summarized (in the given order).
    split_by_snr : bool
        If True, summarize separately per unique |snr| value (sorted
        ascending); otherwise pool SNRs.
    max_rt : int or 'all'
        int: summarize per DT bin, DT = 1..max_rt; 'all': one bin over all DTs.
    apply_quality_filter : bool
        If True (default), also requires get_good_trial_array's standard
        filters (DT >= 2, trial_number >= 10, no wall hit, RT cutoff).

    Returns
    -------
    np.ndarray, shape (n_subjects, n_blocks, n_snrs, n_dt_bins, 3)
        Subjects in sorted order; last axis is [mean |bound|, std |bound|, n trials].
    """
    subject_indices = np.sort(pd.unique(data_table["subject_index"].dropna()))
    abs_bounds = data_table["bound"].abs().to_numpy()
    block_indices = np.sort(data_table["block_index"].dropna().unique()) if blocks == "all" else np.atleast_1d(blocks)

    if split_by_snr:
        abs_snr = data_table["snr"].abs().to_numpy()
        snrs = np.sort(pd.unique(abs_snr[np.isfinite(abs_snr)]))
        l_snrs = (
            np.column_stack([np.isclose(abs_snr, s) for s in snrs])
            if len(snrs) > 0
            else np.zeros((len(data_table), 0), dtype=bool)
        )
    else:
        l_snrs = np.ones((len(data_table), 1), dtype=bool)

    dt_bins = [None] if max_rt == "all" else list(range(1, int(max_rt) + 1))

    correct = data_table["correct"].to_numpy()
    l_good = (correct == 1) if correct_only else (correct >= 0)
    l_good = l_good & (data_table["bound"].to_numpy() != 0)
    if apply_quality_filter:
        l_good = l_good & get_good_trial_array(data_table).to_numpy()

    block_arr = data_table["block_index"].to_numpy()
    subject_arr = data_table["subject_index"].to_numpy()
    dt_arr = data_table["DT"].to_numpy()

    summary = np.full((len(subject_indices), len(block_indices), l_snrs.shape[1], len(dt_bins), 3), np.nan)
    for si, subj in enumerate(subject_indices):
        for bi, blk in enumerate(block_indices):
            l_sb = l_good & (subject_arr == subj) & (block_arr == blk)
            for ni in range(l_snrs.shape[1]):
                for ri, dt in enumerate(dt_bins):
                    lg = l_sb & l_snrs[:, ni] & (True if dt is None else dt_arr == dt)
                    vals = abs_bounds[lg]
                    # ddof=1 to match MATLAB's std(), which normalizes by N-1, not N.
                    summary[si, bi, ni, ri] = (
                        [np.nanmean(vals), np.nanstd(vals, ddof=1), lg.sum()] if vals.size else [np.nan, np.nan, 0]
                    )
    return summary


def get_cp_generative_params(data_table, decimals=6):
    """Generative step mean and SD of the CP task's two fixed-SNR blocks, read from the data.

    The CP task's SNR design, read from the data rather than hardcoded:
    Make_biasCorrection simulates its CP calibration at these values.

    Parameters
    ----------
    data_table : pd.DataFrame
        MXSC data table from `get_data_table` (needs block_index, snr,
        step_std). Canonical blocks 1/2 are the fixed low-/high-SNR blocks.
    decimals : int
        Rounding applied before checking that each block has a single value
        (absorbs floating-point noise in the logged step values).

    Returns
    -------
    dict
        {'low': (mean, std), 'high': (mean, std)} per-step generative
        parameters of the low- and high-SNR conditions.

    Raises
    ------
    ValueError
        If either fixed block is missing or has more than one distinct
        (mean, std) pair across subjects -- i.e. the data mix task designs.
    """
    params = {}
    for name, block in (("low", 1), ("high", 2)):
        rows = data_table[data_table["block_index"] == block]
        means = np.unique(np.round((rows["snr"].abs() * rows["step_std"]).dropna(), decimals))
        stds = np.unique(np.round(rows["step_std"].dropna(), decimals))
        if len(means) != 1 or len(stds) != 1:
            raise ValueError(
                f"Block {block} ({name} SNR) has generative means {means.tolist()} and SDs "
                f"{stds.tolist()}; expected exactly one of each (are task designs mixed?)."
            )
        params[name] = (float(means[0]), float(stds[0]))
    return params


def check_calibration_snrs(calibrated_snrs, data_table, source="calibration", atol=1e-3):
    """Raise if any SNR in the data was not simulated by a calibration.

    Parameters
    ----------
    calibrated_snrs : array-like
        SNRs the calibration was simulated at (e.g. the `snrs` field of
        boundBiasCorrection_CP.mat).
    data_table : pd.DataFrame
        Data table with an `snr` column.
    source : str
        Name of the calibration, used in the error message.
    atol : float
        Absolute tolerance for matching a data SNR to a calibrated one.

    Raises
    ------
    ValueError
        If any finite |snr| in the data is farther than `atol` from every
        calibrated SNR.
    """
    calibrated = np.atleast_1d(np.asarray(calibrated_snrs, dtype=float))
    data_snrs = np.unique(np.round(data_table["snr"].abs().dropna(), 6))
    unmatched = [float(s) for s in data_snrs if not np.any(np.abs(calibrated - s) <= atol)]
    if unmatched:
        raise ValueError(
            f"{source} was simulated at SNRs {np.round(calibrated, 4).tolist()}, but the data "
            f"contain SNRs {unmatched} it does not cover. Rebuild it for the current task design."
        )
