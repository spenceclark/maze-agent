# Experiment `junction_nudge_v4`

Runs planned: 12. Valid runs: v3 6, v4 6. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | v3 | v4 |
| --- | --- | --- |
| success_rate | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| agents_exited | 0.833 [0.5, 1] (n=3) | 1 [0.5, 1.5] (n=3) |
| completion_tick (successes only) | n/a | n/a |
| path_efficiency (exited agents) | 0.885 [0.708, 1] (n=3) | 0.861 [0.637, 1] (n=3) |
| progress_to_exit | 0.585 [0.503, 0.647] (n=3) | 0.597 [0.517, 0.649] (n=3) |
| ticks_since_new_cell (non-exited) | 19.4 [10, 34.2] (n=3) | 32.3 [27, 40] (n=3) |
| stays_before_exit | 40.8 [25.5, 63.5] (n=3) | 24.5 [5.5, 48.5] (n=3) |
| coverage | 0.453 [0.382, 0.58] (n=3) | 0.547 [0.431, 0.653] (n=3) |
| revisit_fraction | 0.425 [0.374, 0.452] (n=3) | 0.357 [0.265, 0.414] (n=3) |
| blocked_moves | 0 [0, 0] (n=3) | 0.333 [0, 1] (n=3) |
| forced_stays | 0 [0, 0] (n=3) | 0.167 [0, 0.5] (n=3) |
| cost_usd | 0.0848 [0.0771, 0.0952] (n=3) | 0.087 [0.0788, 0.0955] (n=3) |

## Differences from `v3`: mean [CI] (n)

| Metric | v4 - v3 |
| --- | --- |
| success_rate | 0 [0, 0] (n=3) |
| agents_exited | 0.167 [-0.5, 0.5] (n=3) |
| completion_tick (successes only) | n/a |
| path_efficiency (exited agents) | -0.0245 [-0.31, 0.292] (n=3) |
| progress_to_exit | 0.012 [-0.022, 0.0437] (n=3) |
| ticks_since_new_cell (non-exited) | 12.9 [-4.33, 26.1] (n=3) |
| stays_before_exit | -16.3 [-28, -6] (n=3) |
| coverage | 0.0949 [0.0347, 0.177] (n=3) |
| revisit_fraction | -0.0683 [-0.108, -0.0378] (n=3) |
| blocked_moves | 0.333 [0, 1] (n=3) |
| forced_stays | 0.167 [0, 0.5] (n=3) |
| cost_usd | 0.00217 [0.000315, 0.00448] (n=3) |
