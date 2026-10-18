# Experiment `qwen35_9b_restate`

Runs planned: 6. Valid runs: v4 3, v6_restate 3. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | v4 | v6_restate |
| --- | --- | --- |
| success_rate | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| agents_exited | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| completion_tick (successes only) | n/a | n/a |
| path_efficiency (exited agents) | n/a | n/a |
| progress_to_exit | 0.222 [0.169, 0.302] (n=3) | 0.148 [0.0192, 0.216] (n=3) |
| ticks_since_new_cell (non-exited) | 26.7 [11.3, 40.7] (n=3) | 18.1 [10, 22.7] (n=3) |
| stays_before_exit | 0.333 [0, 1] (n=3) | 3.67 [1, 5] (n=3) |
| coverage | 0.269 [0.215, 0.306] (n=3) | 0.278 [0.208, 0.326] (n=3) |
| revisit_fraction | 0.785 [0.742, 0.826] (n=3) | 0.775 [0.719, 0.851] (n=3) |
| blocked_moves | 68.3 [54, 76] (n=3) | 61.7 [48, 72] (n=3) |
| forced_stays | 3 [1, 4] (n=3) | 6.33 [6, 7] (n=3) |
| cost_usd | n/a | n/a |

## Differences from `v4`: mean [CI] (n)

| Metric | v6_restate - v4 |
| --- | --- |
| success_rate | 0 [0, 0] (n=3) |
| agents_exited | 0 [0, 0] (n=3) |
| completion_tick (successes only) | n/a |
| path_efficiency (exited agents) | n/a |
| progress_to_exit | -0.0747 [-0.15, 0.0199] (n=3) |
| ticks_since_new_cell (non-exited) | -8.56 [-19, 11.3] (n=3) |
| stays_before_exit | 3.33 [1, 5] (n=3) |
| coverage | 0.00926 [-0.00694, 0.0208] (n=3) |
| revisit_fraction | -0.0105 [-0.0323, 0.0247] (n=3) |
| blocked_moves | -6.67 [-27, 11] (n=3) |
| forced_stays | 3.33 [2, 5] (n=3) |
| cost_usd | n/a |
