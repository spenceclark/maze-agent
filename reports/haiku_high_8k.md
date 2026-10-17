# Experiment `haiku_high_8k`

Runs planned: 12. Valid runs: v4_high_8k 6, v5_high_8k 6. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | v4_high_8k | v5_high_8k |
| --- | --- | --- |
| success_rate | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| agents_exited | 1.17 [1, 1.5] (n=3) | 1.67 [1, 2] (n=3) |
| completion_tick (successes only) | n/a | n/a |
| path_efficiency (exited agents) | 0.862 [0.745, 0.983] (n=3) | 0.882 [0.763, 1] (n=3) |
| progress_to_exit | 0.677 [0.547, 0.75] (n=3) | 0.748 [0.64, 0.887] (n=3) |
| ticks_since_new_cell (non-exited) | 18.6 [8.67, 26] (n=3) | 30.6 [15.5, 38.5] (n=3) |
| stays_before_exit | 9 [0, 26] (n=3) | 20.2 [3, 32.5] (n=3) |
| coverage | 0.559 [0.42, 0.656] (n=3) | 0.51 [0.389, 0.604] (n=3) |
| revisit_fraction | 0.331 [0.227, 0.391] (n=3) | 0.305 [0.268, 0.363] (n=3) |
| blocked_moves | 0 [0, 0] (n=3) | 0.167 [0, 0.5] (n=3) |
| forced_stays | 0.5 [0, 1.5] (n=3) | 0.167 [0, 0.5] (n=3) |
| cost_usd | 0.14 [0.124, 0.149] (n=3) | 0.132 [0.125, 0.141] (n=3) |

## Differences from `v4_high_8k`: mean [CI] (n)

| Metric | v5_high_8k - v4_high_8k |
| --- | --- |
| success_rate | 0 [0, 0] (n=3) |
| agents_exited | 0.5 [0, 1] (n=3) |
| completion_tick (successes only) | n/a |
| path_efficiency (exited agents) | 0.0204 [-0.219, 0.143] (n=3) |
| progress_to_exit | 0.0706 [-0.0171, 0.136] (n=3) |
| ticks_since_new_cell (non-exited) | 12 [-10.5, 29.8] (n=3) |
| stays_before_exit | 11.2 [2, 25] (n=3) |
| coverage | -0.0486 [-0.0625, -0.0312] (n=3) |
| revisit_fraction | -0.0266 [-0.122, 0.0553] (n=3) |
| blocked_moves | 0.167 [0, 0.5] (n=3) |
| forced_stays | -0.333 [-1, 0] (n=3) |
| cost_usd | -0.00767 [-0.0146, 0.000328] (n=3) |
