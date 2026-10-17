# Experiment `landmarks_v4_sonnet`

Runs planned: 6. Valid runs: v4 3, v4_landmarks 3. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | v4 | v4_landmarks |
| --- | --- | --- |
| success_rate | 0.667 [0, 1] (n=3) | 0.333 [0, 1] (n=3) |
| agents_exited | 2.67 [2, 3] (n=3) | 2.33 [2, 3] (n=3) |
| completion_tick (successes only) | 69.5 [68, 71] (n=2) | 73 [73, 73] (n=1) |
| path_efficiency (exited agents) | 0.781 [0.641, 0.899] (n=3) | 0.758 [0.701, 0.824] (n=3) |
| progress_to_exit | 0.975 [0.926, 1] (n=3) | 0.903 [0.782, 1] (n=3) |
| ticks_since_new_cell (non-exited) | 0 [0, 0] (n=1) | 13.5 [0, 27] (n=2) |
| stays_before_exit | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| coverage | 0.634 [0.424, 0.826] (n=3) | 0.623 [0.431, 0.826] (n=3) |
| revisit_fraction | 0.135 [0.0503, 0.18] (n=3) | 0.206 [0.149, 0.26] (n=3) |
| blocked_moves | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| forced_stays | 0 [0, 0] (n=3) | 0.667 [0, 2] (n=3) |
| cost_usd | 1.36 [0.991, 1.73] (n=3) | 1.62 [1.23, 1.87] (n=3) |

## Differences from `v4`: mean [CI] (n)

| Metric | v4_landmarks - v4 |
| --- | --- |
| success_rate | -0.333 [-1, 0] (n=3) |
| agents_exited | -0.333 [-1, 0] (n=3) |
| completion_tick (successes only) | 2 [2, 2] (n=1) |
| path_efficiency (exited agents) | -0.0233 [-0.0755, 0.0603] (n=3) |
| progress_to_exit | -0.0726 [-0.218, 0] (n=3) |
| ticks_since_new_cell (non-exited) | 0 [0, 0] (n=1) |
| stays_before_exit | 0 [0, 0] (n=3) |
| coverage | -0.0116 [-0.0417, 0.00694] (n=3) |
| revisit_fraction | 0.0718 [-0.0301, 0.209] (n=3) |
| blocked_moves | 0 [0, 0] (n=3) |
| forced_stays | 0.667 [0, 2] (n=3) |
| cost_usd | 0.261 [-0.122, 0.875] (n=3) |
