# Screenshot captions

Captured from the spectator viewer with `blog/screenshots.py` (headless Edge, 2x scale).

| File | Game | Suggested caption |
| --- | --- | --- |
| `maze-sonnet-12x12-team-success-t110.png` | `efb5bfcde844`, turn 110 | Sonnet's first team success on the current setup. Trails show each agent's whole route; B has just stepped onto the exit after following C's directions from the picture landmark. |
| `maze-haiku-17x17-team-success-t236.png` | `1c461f2ef226`, turn 236 | Haiku on 17x17 with 14 landmarks: B reaches the exit at turn 236 to complete the team objective. A and C (dashed ring = sharing a cell) are on the rope landmark. |
| `maze-haiku-15x15-missed-gateway-t600.png` | `ec6580b5c45c`, turn 600 | The 15x15 failure. The whole exit region (top left, no trails) is reached through one cell on the south edge; all three agents passed it twice and kept following the boundary. |
| `radio-sonnet-landmark-relay.png` | `efb5bfcde844`, turns 88-96 | The landmark relay: C reaches the exit and radios it relative to the picture with a step-by-step route; B finds the picture at turn 95 and follows it. |
| `radio-haiku-10x10-waiting-for-coordinates.png` | `ebe880ccf91e`, turns 41-60 | Haiku's stalemate: C has the exit relative to the quilt; A and B have calibrated their own frames on the helmet, and everyone waits for coordinates instead of going to the quilt. |
| `notebook-haiku-meeting-offset.png` | `ed1ea6a5c483`, turn 76 | With the meeting alert, C meets B on the candle and works out the frame offset (correctly), then converts the exit into B's frame. The lines above show the beacon habit it never quite dropped. |
| `notebook-qwen-temperature-lock-in.png` | `211579962f41`, turns 9-16 | Qwen at temperature 0.2: the same note every turn, correctly recording `W=wall`, followed by the same move west into it. It continued for 71 turns. |
| `notebook-haiku-frontier-list.png` | `3e75a6a13206`, turns 41-44 | Haiku with coordinates keeping a depth-first frontier: "Untried exits in my frame: [0,0] S, [0,3] S, [-2,3] W", then heading back to them. |
