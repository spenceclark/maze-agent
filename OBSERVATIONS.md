# Observations

Notes on things that surprised us while building phases 1–5. **Most agent-behaviour notes come from one pilot run**
(n = 1, one seed, one model). Treat them as hypotheses to test with the phase 6 batch runner, not as results.

Pilot: run `7a0a23e416da`, `configs/pilot_haiku.json`. Three `claude-haiku-5-5` agents on a 7×7 perfect maze
(seed 20261017), barrier timing, 80-tick horizon, all default budgets, `native` output mode. Oracle minimum is
22 ticks; per-agent shortest spawn→exit paths were A 12, B 22, C 20.

| Agent | First exit | Moves | Blocked | Stays | Revisit fraction | Path efficiency | Notebook at t80 | Revisions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | t12 | 12 | 0 | 68 | 0.00 | 1.00 | 1,308 B | 15 |
| B | t31 | 30 | 1 | 49 | 0.20 | 0.73 | 2,869 B | 33 |
| C | never | 73 | 7 | 0 | 0.81 | — | 5,244 B | 64 |

All 240 decisions were schema-valid and accepted. No timeouts, refusals, or rejected notebook writes. Cost $0.12.

## Agent behaviour

### The notebook can override the agent's own current perception
This was the most surprising result. Agent C's notebook repeatedly recorded **observations that contradict what
the observation actually said that turn**, and C then acted on the notebook rather than the observation:

- From T17 to T21, C wrote the same line every tick: "N,E open; S wall; W brick". At T20 and T21 the real
  observation was N `interior_wall`, E open, S open, W brick. C moved N into the visible wall at T20, then did it
  again at T21, even though `last_action` said `blocked`. Only at T22 did it note "N wall (N move blocked T21)".
- At T54 C wrote "N,S open; E,W walls" while standing in a dead end (only S open), and moved N into the wall.
- B made the same mistake once. At T16 it was "backtracking S" according to its own plan while S was an interior
  wall.

All 8 blocked moves in the run were attempts to walk through an edge the agent could see was closed. The pattern
looks like copy-forward: the model re-emits its previous log line with a new tick label instead of reading the new
`local` block. This is a memory-management failure the experiment is meant to surface, and here it surfaced
quickly.

### Compaction lost information and the agent noticed
At T11 C rewrote its whole notebook from about 1 KB down to about 300 bytes, its only compaction in the run. It
replaced its history with two invented cell types, "X" and "Y", keyed by edge pattern and approximate exit
distance. One tick later it wrote "Notebook labels X/Y look swapped vs obs, trust obs". So the lossy summary was
wrong, and the agent caught it.

### Nobody built a coordinate system
The spec expected agents might infer a private coordinate frame (§4.2). None did. All three kept prose journals:
"T23 obs: …; exit 3.2; came from W. Trying S." A recorded its route as a move list from its spawn (E4, N4, W2,
N2). No agent used JSON, a grid, or (x, y) pairs.

### Spawn-relative directions are mostly useless to peers, but boundaries let one agent reuse them
A radioed "Route from spawn: E,E,E,E,N,N,N,N,W,W,N,N" at T13 and kept repeating it. The route only helps
someone standing on A's path.

- **B used it.** B reached the bottom (brick) row near the south-east corner at T20, then walked A's exact last
  11 moves: E, E, E along the brick to the corner, N four times up the east edge, W, W, N, N. The outer brick
  apparently worked as a shared landmark. This matches the spec's remark that boundary materials support
  inference. The trajectory is consistent with deliberate route-following, but we haven't shown causation.
- **C could not use it, and said so.** C wrote that "our spawn position is unknown". At T36 and T71 it asked A
  and B for directions relative to the exit instead: "from EXIT, which moves reach a cell with N,S open and E,W
  closed?" That was the right question.

### "Guiding" meant standing still and repeating themselves
After reaching the exit, A and B stayed on the exit cell for the rest of the run (68 and 49 stays). They spent 49
consecutive ticks co-located. They radioed at nearly every eligible opportunity: 11 messages each, against a
maximum of 14 under the cooldown. 20 of the 30 messages in the run restate A's spawn route almost word for
word. B's messages echo A's from the previous tick.

Neither one:
- answered C's question about directions from the exit;
- moved toward C, even though `peer_ranges` gave them C's distance every tick;
- copied anything useful from the other's notebook, despite reading it every tick.

Under `all_reach_exit`, holding the exit adds nothing; a visit already counts. The agents read "stay at exit to
guide" as helpful, and it wasn't.

### Distance used as a gradient, and as a fingerprint
- **A** reached the exit in exactly the shortest 12 moves. Its notes show it treating `exit_distance_tenths` as a
  gradient: it pushed east even while the distance rose 6.0→6.3, then turned north once the distance began
  falling. With n = 1 we can't tell how much of this was luck.
- **C** used distance to tell apart cells that look alike: "E from similar cell gave 2.8 before". But C visited
  only 15 distinct cells in 73 moves (revisit fraction 0.81). It bounced between a few junctions that share an
  edge pattern and exit distance, the aliasing problem a coordinate frame would solve. C never reached the
  bottom-row/east-edge corridor where the shared route could have been picked up.

### Notebook growth and input cost
C appended about 65 bytes per tick and would have hit the 8 KiB cap around tick 125. A's notebook barely grew
after it reached the exit.

Input tokens track notebook size: C's prompt grew from 1.85 k tokens at T1 to 4.35 k at T80. Input was about 10×
output overall (780 k vs 78 k tokens). Median output per decision was about 150 tokens. Longer runs will be
dominated by input cost, which scales with how much agents choose to remember.

## Model and provider notes (Claude Haiku 5.5)
- **Sampling:** Haiku 5.5 rejects non-default `temperature`/`top_p` with a 400. LLM configs for it must leave
  `sampling` empty, so "temperature 0" comparisons are not possible on this model.
- **Thinking:** it thinks adaptively by default (effort `medium`), and the provider reports no separate
  reasoning-token count (`reasoning_tokens` stays null). Any thinking is folded into output tokens and counts
  against `max_output_tokens`.
- **Output modes:** both `native` structured output and `tool` output worked. In a single smoke call, tool mode
  used 331 output tokens against 119 for native mode, for a similar action. That's n = 1, but worth measuring
  across conditions, because tool mode is the default.
- **Latency:** p50 2.5 s, max 6.1 s. The default 30 s fixed deadline is very generous for this model. The
  80-tick pilot took about 10 minutes in barrier mode; fixed-deadline mode would have taken about 40.

## Baselines (15×15, seed 20261017, oracle 105 ticks)
| Policy | Outcome |
| --- | --- |
| `wall_follower_v1` | all reached exit at t217 |
| `dfs_bounded_v1` | all reached exit at t326, coverage 0.94 |
| `random_open_v1` | tick limit at 500, coverage 0.54 |

The wall follower beat bounded DFS. Each DFS agent explores almost the whole maze on its own (no sharing), while
the right-hand rule happened to suit this maze.

Logging moves "one tick late" turned out to be the natural design for notebook-only memory. A decision can't see
its own outcome, so DFS appends a move to its log only once the next observation confirms it. LLM agents
independently did the same thing ("t13: moved E, arrived from W").

## Engineering surprises
- **Duplicate JSON keys:** Pydantic's JSON parser accepts duplicate keys (last one wins), so the spec's
  "no duplicate keys" rule needs a stdlib `json.loads(object_pairs_hook=…)` pre-pass.
- **Provider check vs strict parsing:** PydanticAI validates the action too, but we re-parse the raw tool/JSON
  text with the strict contract parser so every provider meets the same bar.
- **Request counting:** with `retries=0` and SDK clients built with `max_retries=0`, every one of the 240
  invocations made exactly one provider request (checked from usage records).
- **Context preflight is very conservative:** the worst-case bound assumes notebooks full of NUL characters (6
  bytes each when JSON-escaped) and one token per byte. That comes to about 156 k tokens for default caps, while
  real prompts were 2–5 k. As written it would reject most 32 k-context local models. Options: count with the real
  tokenizer, or disallow control characters in notebooks.
- **Uvicorn WebSockets:** plain `uvicorn` with no `websockets`/`wsproto` installed answers WebSocket upgrades
  with an HTTP 404. FastAPI's `TestClient` hides this. The viewer sub-agent found it in a real browser.
- **Starlette `TestClient` buffers streaming responses,** so live SSE can't be tested through it. The live
  reconnect test drives the stream generator directly.
- **Read straddling a commit:** reading `committed_tick` and the last sequence in two queries could skip a tick
  for a client that bootstraps then subscribes. They now come from one SQL statement.
- **Pyright hashability:** pyright doesn't know frozen Pydantic models are hashable. `Position` got an explicit
  `__hash__`.
- **Smaller gotchas:**
  - `load_dotenv()` searches from the calling file's directory, not the working directory.
  - `openapi-typescript` 7.13 fails under TypeScript 7, so the UI pins TypeScript 5.9.
  - On Windows, running `uv sync` while a run is going risks file locks, so dependency changes waited until the
    pilot finished.

## Prompt caching (added after the pilot, prompt `maze_agent_v2`)
The pilot sent each observation as one JSON blob, so no part of the prompt was reusable between ticks. Version 2
splits the user message into three blocks, from most to least stable:
1. the agent's own notebook;
2. co-located notebooks;
3. everything that changes every tick.

On Anthropic it sets two cache breakpoints, one after the system instruction and one after the notebooks.
Caching reuses identical input only, so it doesn't break the fresh-invocation rule.

A 15-tick live check on the pilot maze showed:
- **The fixed prefix is always reused.** After tick 1, every request read about 1.43 k tokens (system
  instruction plus output schema) from the cache.
- **Notebooks are reused only when unchanged.** A notebook is written to the cache when it changes, at a 25%
  premium on those tokens, and read back when it doesn't (C at T14–15: 1,954 read, 0 written).
- **Cost:** input cost for ticks 1–15 fell from $0.0097 to $0.0051 on similar input volume (about −47%), and
  total cost by about 26%. On Haiku, output tokens (5× the input price) are now the larger share.
- **Agents that rewrite their notebook every tick benefit least.** Their notebook block is re-written each
  time, which makes notebook churn a cost as well as a memory question.

`Usage` and `RunMetrics` now record `cache_read_tokens` and `cache_write_tokens`; both are included in
`input_tokens`. Cost comes from the provider's usage, so cached tokens are priced at their own rates. OpenAI-
compatible servers and Ollama ignore the breakpoints but benefit from the stable-first order through their own
prefix reuse.

## Context sizing for local models
The original preflight assumed one token per byte and notebooks full of characters that JSON-escape to six
bytes. That gave about 156 k tokens for default caps and would have rejected every 32 k model.

The pilot's real prompts ran 1.67–1.91 bytes per token. Preflight now uses a per-agent
`context_bytes_per_token`: default 1.5, with 1.0 as the strict bound. It also only counts peer notebooks when
meeting notebooks are enabled. With default caps a worst-case turn needs about 22 k tokens, so 32 k models pass
and 8 k models don't.

An 8 k model fits with:
- `notebook_cap_bytes: 2048`;
- `meeting_notebooks_enabled: false`;
- `max_output_tokens: 1024`.

Every real request is also checked before sending. One that would overflow becomes a forced no-op
(`provider_error`) instead of being sent, because Ollama truncates oversized prompts silently. Ollama's context
length must also be raised server-side (`OLLAMA_CONTEXT_LENGTH` or the Modelfile). Its OpenAI-compatible
endpoint can't set it per request, and the default is far below 8 k on many installs.

## Worth testing next (phase 6)
- **Notebook trust:** add a turn-level self-check prompt variant ("re-read `local` before moving"). Measure
  blocked-into-visible-wall rate as a perception-vs-memory reliability metric.
- **Ablations:**
  - radio off vs on: does B's route-following survive without A's broadcasts?
  - meeting notebooks off: A and B never used them here.
  - `first_exit` vs `all_reach_exit`: does "hold the exit" change?
- **Prompting:** whether stating plainly that "a previous visit satisfies the objective" stops finished agents
  from camping on the exit.
- **More seeds and replicates** before believing any of the above: path efficiency 1.0 for A is a single draw.
