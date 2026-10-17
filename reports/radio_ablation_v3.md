# Experiment `radio_ablation_v3`

Runs planned: 18. Valid runs: radio_on 9, radio_off 9. Resampling unit: seed. Intervals are 95% percentile bootstrap.

## Estimates: mean [CI] (n)

| Metric | radio_on | radio_off |
| --- | --- | --- |
| success_rate | 0 [0, 0] (n=3) | 0 [0, 0] (n=3) |
| agents_exited | 0.889 [0.667, 1] (n=3) | 1.11 [0.333, 1.56] (n=3) |
| completion_tick (successes only) | n/a | n/a |
| path_efficiency (exited agents) | 0.924 [0.771, 1] (n=3) | 0.883 [0.825, 0.923] (n=3) |
| coverage | 0.446 [0.296, 0.572] (n=3) | 0.501 [0.419, 0.588] (n=3) |
| revisit_fraction | 0.399 [0.362, 0.424] (n=3) | 0.382 [0.293, 0.541] (n=3) |
| blocked_moves | 0.222 [0, 0.333] (n=3) | 0 [0, 0] (n=3) |
| forced_stays | 0 [0, 0] (n=3) | 0.111 [0, 0.333] (n=3) |
| cost_usd | 0.0849 [0.079, 0.0913] (n=3) | 0.072 [0.0671, 0.0802] (n=3) |

## Differences from `radio_on`: mean [CI] (n)

| Metric | radio_off - radio_on |
| --- | --- |
| success_rate | 0 [0, 0] (n=3) |
| agents_exited | 0.222 [-0.667, 0.667] (n=3) |
| completion_tick (successes only) | n/a |
| path_efficiency (exited agents) | -0.0411 [-0.175, 0.129] (n=3) |
| coverage | 0.0548 [-0.0764, 0.123] (n=3) |
| revisit_fraction | -0.0169 [-0.111, 0.129] (n=3) |
| blocked_moves | -0.222 [-0.333, 0] (n=3) |
| forced_stays | 0.111 [0, 0.333] (n=3) |
| cost_usd | -0.0129 [-0.0172, -0.0102] (n=3) |
