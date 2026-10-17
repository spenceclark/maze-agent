# Experiment `landmarks_v4`

Runs planned: 12. Valid runs: v4 6, v4_landmarks 6. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | v4 | v4_landmarks |
| --- | --- | --- |
| success_rate | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| agents_exited | 1.17 [1, 1.5] (n=3) | 1 [0.5, 1.5] (n=3) |
| completion_tick (successes only) | n/a | n/a |
| path_efficiency (exited agents) | 0.933 [0.89, 1] (n=3) | 0.898 [0.765, 0.969] (n=3) |
| progress_to_exit | 0.672 [0.647, 0.687] (n=3) | 0.737 [0.71, 0.789] (n=3) |
| ticks_since_new_cell (non-exited) | 8.08 [5.5, 10.2] (n=3) | 15 [3.25, 25.5] (n=3) |
| stays_before_exit | 0.333 [0, 0.5] (n=3) | 12.5 [0, 37.5] (n=3) |
| coverage | 0.547 [0.465, 0.674] (n=3) | 0.593 [0.542, 0.635] (n=3) |
| revisit_fraction | 0.345 [0.248, 0.393] (n=3) | 0.324 [0.203, 0.422] (n=3) |
| blocked_moves | 0 [0, 0] (n=3) | 0.333 [0, 1] (n=3) |
| forced_stays | 0.167 [0, 0.5] (n=3) | 0 [0, 0] (n=3) |
| cost_usd | 0.0847 [0.0811, 0.0884] (n=3) | 0.0899 [0.0793, 0.0986] (n=3) |

## Differences from `v4`: mean [CI] (n)

| Metric | v4_landmarks - v4 |
| --- | --- |
| success_rate | 0 [0, 0] (n=3) |
| agents_exited | -0.167 [-0.5, 0] (n=3) |
| completion_tick (successes only) | n/a |
| path_efficiency (exited agents) | -0.035 [-0.235, 0.0787] (n=3) |
| progress_to_exit | 0.0649 [0.027, 0.106] (n=3) |
| ticks_since_new_cell (non-exited) | 6.92 [-5.25, 20] (n=3) |
| stays_before_exit | 12.2 [-0.5, 37] (n=3) |
| coverage | 0.0451 [-0.0382, 0.135] (n=3) |
| revisit_fraction | -0.0204 [-0.0457, 0.0288] (n=3) |
| blocked_moves | 0.333 [0, 1] (n=3) |
| forced_stays | -0.167 [-0.5, 0] (n=3) |
| cost_usd | 0.00518 [-0.00182, 0.0102] (n=3) |
