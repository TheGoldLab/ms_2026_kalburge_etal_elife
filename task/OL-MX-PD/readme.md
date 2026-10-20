# PigeonTask (cohorts 1, 2 and 4: OL, MX, PD)

The PsychoJS task run for cohort 1 (OL, blocked SNR), cohort 2 (MX, mixed SNR) and cohort 4 (PD,
predefined bound). It was exported from PsychoPy Builder (`PigeonTask.psyexp` compiles to
`PigeonTask.js`) and deployed on Pavlovia. To run it locally or through Prolific, see
[../MXSC/README.md](../MXSC/README.md); the setup is the same.

## The condition files here are not the deployed ones

`PigeonTask.js` is the code that was run. The condition files in `Resources/` are an earlier
pilot version, and they do not match what participants saw:

- `PigeonTaskConditions.xlsx` has 4 blocks of 200 steps and no step penalty. The deployed files had
  6 blocks of 600 steps (800 for PD), the last block of each half with a 30-step error penalty.
- `PigeonSNRSet01Conditions.xlsx` and `PigeonSNRSet02Conditions.xlsx` hold one step mean each
  (0.05 and 0.15). MX's deployed files instead had both 0.05 and 0.15 in set 1 (mixed SNR) and 0.10
  in set 2.

The deployed files were not kept. The tables below give their settings, reconstructed from the
raw data: each participant's file records the block's `tc_*` columns at the end of every block, and
the step mean and SD (`ssc_step_mean`, `ssc_step_std`) on every trial. All 60 files in each cohort
agree. Every block has a step SD of 0.15, starts each trial at a cost of 1 step and no coins, and
gives 1 coin per correct choice. For PD, the trial ends when the pigeon reaches the bound the
participant set.

Columns:
- **Mean:** |step mean|.
- **Error penalty:** coins and steps lost per error (`tc_coins_lost_per_error`, `tc_steps_lost_per_error`).
- **Bonus target:** `tc_coins_max`, the coins needed for the block's bonus (shown as "Target number of
  coins for bonus"). PD instead pays the bonus when the set bound lies between
  `tc_predefined_bound_min_bonus` and `tc_predefined_bound_max_bonus`.

**Cohort 1 (OL):** `tc_task_type = online`, 600 steps per block

| Block | `tc_block_name` | SNR set | Mean | Error penalty | Bonus target |
|---|---|---|---|---|---|
| 1 | lowSNRlowcost | 1 | 0.05 | 0 coins, 0 steps | 125 |
| 2 | lowSNRhicost | 1 | 0.05 | 4 coins, 0 steps | 23 |
| 3 | lowSNRto | 1 | 0.05 | 0 coins, 30 steps | 30 |
| 4 | highSNRlowcost | 2 | 0.15 | 0 coins, 0 steps | 170 |
| 5 | highSNRhicost | 2 | 0.15 | 4 coins, 0 steps | 115 |
| 6 | highSNRto | 2 | 0.15 | 0 coins, 30 steps | 105 |

**Cohort 2 (MX):** `tc_task_type = online`, 600 steps per block; in blocks 1–3 each trial's mean is
0.05 or 0.15

| Block | `tc_block_name` | SNR set | Mean | Error penalty | Bonus target |
|---|---|---|---|---|---|
| 1 | mixSNRnocost | 1 | 0.05 / 0.15 | 0 coins, 0 steps | 150 |
| 2 | mixSNRhicost | 1 | 0.05 / 0.15 | 4 coins, 0 steps | 45 |
| 3 | mixSNRto | 1 | 0.05 / 0.15 | 0 coins, 30 steps | 50 |
| 4 | avgSNRnocost | 2 | 0.10 | 0 coins, 0 steps | 150 |
| 5 | avgSNRhicost | 2 | 0.10 | 4 coins, 0 steps | 70 |
| 6 | avgSNRto | 2 | 0.10 | 0 coins, 30 steps | 65 |

**Cohort 4 (PD):** `tc_task_type = predefined_commit`, 800 steps per block

| Block | `tc_block_name` | SNR set | Mean | Error penalty | Bonus bound range |
|---|---|---|---|---|---|
| 1 | lowSNRnocost | 1 | 0.05 | 0 coins, 0 steps | −0.00001–0.0025 |
| 2 | lowSNRhicost | 1 | 0.05 | 4 coins, 0 steps | 0.39999–0.6 |
| 3 | lowSNRto | 1 | 0.05 | 0 coins, 30 steps | 0.265–0.375 |
| 4 | highSNRnocost | 2 | 0.15 | 0 coins, 0 steps | −0.00001–0.01 |
| 5 | highSNRhicost | 2 | 0.15 | 4 coins, 0 steps | 0.13–0.2 |
| 6 | highSNRto | 2 | 0.15 | 0 coins, 30 steps | 0.19–0.255 |

The analysis code takes its block settings from `pigeon.simulation.BLOCK_DEFAULTS` and
`BLOCK_DEFAULTS_PD`, which match these tables, not from the files in `Resources/`.
