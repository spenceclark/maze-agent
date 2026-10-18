# Observations

## Summary: what didn't work, and how much shepherding the model needed
This is a running digest for write-ups; the detailed, chronological evidence is below, and the batch tables
are in `reports/`. All of these are 12×12 or smaller mazes with three agents on Claude Haiku 5.5 unless noted.
Batches use 3 seeds, so intervals are wide.

**The shepherding ladder.** Each row is a failure we saw, the nudge we tried, and what changed.

| # | Failure observed | Shepherding tried | What changed | Still broken |
| --- | --- | --- | --- | --- |
| 1 | Agents wrote stale notes and trusted them over what they could see: 8 moves into visible walls in 240 decisions (first pilot) | Prompt v2: the current observation moved into its own final block, after the notebooks (done for caching) | Moves into visible walls dropped to 2 in 4,320 decisions in later batches | Not a controlled test; the layout change is a plausible cause, not a proven one |
| 2 | Straight-line distance followed greedily: agents parked on low-reading dead ends, one 2.2 cells away in a straight line but 39 moves by path | Prompt v3: the rules say distance ignores walls, so a local minimum can be a dead end | One agent improved in a single run, but its notes never cited the rule. Batches showed no change in greedy reversals | **Didn't work.** Knowing the rule didn't change the behaviour |
| 3 | Agents on the exit radioed greedy advice ("avoid E", "hold at 5.0") and camped there as "beacons" | Radio-off ablation (18 runs) | No change in outcomes. With radio, agents still searching stood still ~17 more turns, and cost was ~15% higher | **Removing bad advice didn't remove the greed**; it's the model's own habit. Radio mostly bought waiting |
| 4 | Aimless re-exploration, with no record of which branches were tried | Prompt v4: note each junction and which exits were tried; prefer an untried one | Habit adopted by 17 of 18 agents (1 of 18 before). Coverage +9.5 points, revisits −6.8 points, ~16 fewer STAYs | **Progress toward the exit unchanged.** Better bookkeeping, same stalls |
| 5 | Cells all look alike, and routes told "from my spawn" are useless to anyone else | Landmarks: 10 unique labels on fixed cells | Used as place names ("north corridor above mirror is exhausted"). Best progress toward the exit +6.5 points | **No more agents exited.** Landmarks were rarely shared (10 of 155 radio messages) |
| 6 | All of the above | **Swap model:** Sonnet 5.5 with no prompt changes (1 single run, then a 6-run batch) | Teams met the objective in **3 of 6** batch runs, against 0 of 12 for Haiku. 85% of agents reached the exit, against 36%. Far fewer back-and-forth moves (1.8 vs 4.3 per agent) and no waiting | Cost ~16–20×. **Landmarks didn't matter for Sonnet** (2 of 3 succeeded without them, 1 of 3 with). The model, not the scaffolding, made the difference |
| 7a | Can context alone push Haiku into Sonnet's habits? | Prompt v5: spell out coordinates, exit estimation and landmark-anchored routes | **Adopted in form by 100% of agents** (0% before); 83% estimated the exit's position | **Progress got worse (−0.10).** The coordinates drifted (only 28% of noted positions correct), and agents then distrusted their own maps |
| 7b | Is it a matter of reasoning budget? | Higher thinking effort (`effort: high`), with v4 and with v5 | Haiku's first team successes: 2 of 12 runs, both on the easiest seed. +0.5 agents reaching the exit per run. With v5, coordinates were more accurate (42%) | The extra thinking overflowed the 2,048-token cap: 34 and 74 cut-off decisions became forced STAYs. Cost +40–57% |
| 8 | Does a cheap reasoning model already have Sonnet's habits? | DeepSeek v4.1 Flash via OpenRouter, plain v4 + landmarks, 8k cap (3 runs) | **Unprompted, every agent kept coordinates and estimated the exit's position,** and shared routes from landmarks about as often as Sonnet. Cost $0.30 per run | At a 60 s window, ~25% of turns were lost to timeouts and truncations (0 of 3). **With a 600 s window: no timeouts, 1 of 3 teams succeeded (t53, the fastest finish of any model)**, 1.67 agents exited. Still ~13% of turns lost to truncation at 8k. $0.38 per run |
| 9 | How does a strong local model do? | Qwen3.5-9B (Unsloth IQ4) on Ollama, reasoning off, 8k context, v4 + landmarks (3 runs; meeting notebooks off to fit 8k) | Ran reliably: 4 failed decisions in 720, about 25 s per decision with 9 requests queued on one GPU, $0 **33% of decisions walked into a visible wall** (other models ≤0.3%); no agent reached the exit. Follow-ups: queuing ruled out, and the restate-edges prompt (v6) didn't help. Output field order is untested: Ollama emits keys alphabetically, so `move` always comes first. With reasoning on, wall moves vanished, but half the decisions never finished (see below) |
| 10 | Qwen's splices missed: 30 of 240 notebook edits rejected for a stale revision or a bad offset, leaving notes out of order | `notebook_ops: append_rewrite`: append or rewrite fields, and the engine places the text (single games, same seed) | No more offset or revision errors. After hardening (plain-text notebooks, `"null"` counts as no change), no notebook wipes | **Qwen filled both fields in 20 of 240 decisions despite the rule, so 21 of 22 rewrites were cancelled.** Notebooks filled to the cap by t34–49 and the final 84 appends were rejected. **Then a rolling log (`append_log`, one field): 206 of 240 notes accepted, 12 rejections, no wipes; the oldest lines rolled off from t30–54.** Wall hits 23%, no exits, coverage 0.24 (splice 25%, A exited, 0.26). The bookkeeping is fixed; navigation isn't. Single games, not a controlled comparison |
| 11 | Qwen walks into walls ~25% of the time, much of it sampling noise | Temperature 0.2, reasoning still off (replay of 100 recorded decisions, then one full rolling-log game) | In replay, wall moves fell from 24% to 9% | **In a real game they rose to 56%.** With little randomness the agent copies its last note and repeats the same blocked move: C walked W into a wall it had written down 71 turns in a row, B 35. Exploration collapsed (coverage 0.17, team distinct cells 24 against 35). Default temperature was what broke these loops |
| 12 | Did the Qwen fixes help Haiku? | Rolling-log notebook on Haiku, otherwise the same config as the earlier Haiku runs (v4 + landmarks, seed 202611017; one game against 5 earlier splice runs) | Nothing to fix: Haiku's splices were never rejected, and walls stayed near zero | **No gain, maybe worse.** Only A (5 cells from the exit) got out; B had exited in 3 of 5 splice runs. Coverage 0.35 (0.36–0.76 before), reversals 26 (4–14). It wrote a note every turn, so notebooks filled and every prompt changed at the notebook block. **Cost $0.14 against $0.07–0.09**, with cache writes tripled |
| 13 | No shared frame, and no memory of where they've been | `coordinates_enabled`: exact [x, y] from each agent's own start plus a 30-turn trail, a rule on lining frames up via a shared landmark or cell, and a quieter rolling log (one game each, Haiku and Qwen) | **Haiku solved the 'where':** B and C each placed the exit exactly in their own frames from distance readings. B found the exact offset to A's frame by using the exit as the shared cell. Exploration rose (92 cells against 58, back-and-forth 19 against 26) and notes fell from 238 to 170 | **No one new reached the exit:** B knew the exit was at (-6,-2) but found no route to it in 80 turns. Qwen wrote 'Must break out of this loop' 59 times and kept looping; its wall hits were 37%. The bottleneck is now route-finding |
| 14 | Why is route-finding so poor? Measured at junction revisits | Ground truth from trajectories: when back on a junction with an untried open exit, how often does the agent take one it has already used? | **Sonnet 3%, DeepSeek 27%, Haiku 40%, Qwen 58%.** In Haiku's bad choices, it wrote "Trying X (untried)" about an exit it had used | **Two bookkeeping gaps:** (1) cells have no identity, so a revisit is logged as a new cell; (2) the exit it arrived through is never marked tried. Stale duplicate lines aren't the main issue. Sonnet names cells (W1, W2…) and recognises them. Haiku with coordinates: 0 of 8 (small sample) |
| 15 | Our own wording hamstrung them: "trail lists where you were on each of the last 30 turns" | Prompt v7 (the exit you arrived through counts as tried), then the trail rule reworded: "ends with last turn's cell, never includes where you are now" (Haiku + coordinates, same seed) | v7 was adopted ("E open (came from)") but measured nothing new: used-exit choices were already 0%. **The wording fix removed all doubt notes (22 per game → 0)** and gave the best exploration so far: 110 distinct cells (85–92 before), coverage 0.45, back-and-forth 11 (19–22) | Still only A exits. C needs 52 moves even with a perfect map and was still finding new cells at t80. **The 80-turn horizon now binds**; the default for 12×12 is 320 |
| 16 | Are the distance readings making them bounce? About 60% of Haiku's reversals came straight after a move that raised the exit reading | `distance_sensors: none`: no exit distance and no peer ranges, and the distance rule replaced by "you have no distance sensors" (Haiku, v7 + coordinates, same seed; one game) | **Coverage 0.53, the best Haiku game yet** (0.45 with distances), 115 distinct cells, back-and-forth about the same (14 against 11). Landmarks were mentioned far more (16 notes and 8 radio messages, against 6 and 1), because they became the only shared reference | Still only A exits, and nobody meets. Without distances, B and C can't locate the exit, so A's route home in A's frame is useless until they find a shared cell. The horizon still binds: C was finding new cells at t80 |
| 17 | Agents who reach the exit camp on it as a "beacon" and help nobody. Agents swap landmark coordinates but never do the subtraction | Prompt v8 = v7 plus "once you have reached the exit, standing on it helps nobody… head back along your known route to find a teammate… compare positions… give them the route in their own frame" (Haiku, no distances, coordinates; one game) | **A left the exit** (STAYs 42 against 75). **The first explicit landmark calibration:** at t51 B worked out "B = C + (0,4)" (correct) and converted C's landmarks into its own frame. Coverage 0.62, the best Haiku game | A walked out, then waited at its own start (unknown to anyone else) for the last 37 turns, radioing the same route 13 times. It never went to a landmark, so nobody could convert A's exit into their frame. Still only A exits |
| 18 | The exit-finder never gives others a reference they can use | Prompt v9 = v8 plus "give positions relative to a landmark… if you know where the exit is, visiting a landmark… is one of the most useful things you can do" (Haiku, no distances; one game) | **The searchers adopted it:** C asked A for "your exit position relative to the piano", B for A's position "relative to the statue" | **The exit-finder didn't.** A went straight back to its own start and waited there for 69 turns "as rendezvous". It described the exit relative to its start ("2 west and 1 north of A's start"), a place only A can find, and never visited a landmark. Coverage fell to 0.44 (0.62 with v8). Still only A exits |
| 7c | Was the output cap hiding the gain? | High effort with an 8,192-token cap | Truncations essentially gone (≤0.5 forced STAYs per run); coordinate accuracy 46% with v5 | **No team successes in 12 runs; exits and progress unchanged.** The 7b wins look like seed luck. Room to think didn't close the gap |

**What Haiku did well unprompted:**
- **Notebook use from turn one:** concise journals, one line per turn.
- **Logging one tick late:** it recorded moves only once the next observation confirmed them, as the
  bounded-DFS baseline does.
- **Radioing** useful facts, such as the exit cell's walls.
- **Occasional self-correction** ("labels look swapped vs obs, trust obs").
- **Checking a peer's claim with its sensors:** "My exit dist 3.2 equals my range to A, so A on exit is
  consistent".

**Model or context? Mostly the model.**
- **Context changes what Haiku writes and does.** Each nudge (v3, v4, v5, landmarks) was adopted, often by
  every agent, and moved exploration metrics.
- **None turned into reaching the exit.** On the 12×12, 80-tick setup, 2 of 78 Haiku batch runs met the team
  objective, across every prompt, effort and cap variant.
- **Sonnet did it at default settings:** 3 of 6 in the batch, plus 1 single run.
- **More thinking didn't close the gap.** At an 8,192-token cap Haiku wrote ~550 output tokens per decision,
  Sonnet ~225; Haiku's coordinates stayed under 50% correct, against ~98% for Sonnet agents tracking from their
  start.
- **What Haiku lacks:** precise state-tracking (dead reckoning over 20+ moves) and decisive exploration. It
  doesn't lack strategy: it can be told the right strategy, and it complies.

**What Haiku almost never did without explicit help:**
- **Keep coordinates.** 0–17% of agents, and only the weakest form.
- **Estimate where the exit is** from several readings.
- **Anchor shared routes to something peers can find.** It almost always used its own spawn.
- **Answer a peer's specific question,** or move toward a stuck peer.
- **Commit to a branch** while the distance reading rose.

**Failure modes that kept recurring:**
- **Copying stale notes forward.**
- **Retelling drift:** routes shortened or garbled when re-radioed from memory, even though the notebook
  was right.
- **Camping on the exit** as a "beacon" that adds no information, because the peer range to a beacon equals
  the exit distance.
- **Greedy advice** to peers in different places, including advice that contradicted the rule just quoted.
- **Note-taking lapses** followed by a two-cell back-and-forth that lasted 38 ticks.
- **Hidden thinking using up the output budget:** about 1 decision in 3,000 was cut off.

**Lessons about running the experiment:**
- **Single runs mislead.** B's large v3 improvement didn't replicate.
- **"Ran out of time" was wrong.** Agents stalled by tick ~24 and looped; a longer horizon would have measured
  longer loops.
- **Behavioural metrics moved where outcomes didn't.** STAYs before exiting, ticks since a new cell and best
  progress toward the exit showed changes that success rate couldn't.
- **Cheap prompt nudges change behaviour reliably,** and agents adopt them almost universally. They don't
  automatically change outcomes.

---

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

## Second pilot: run `6c7068296716` (12×12, seed 202611017, prompt v2, 80 ticks)
Shortest spawn→exit paths were A 5, B 28, C 52, so the 80-tick horizon left C almost no slack.

| Agent | First exit | Moves | Stays | Blocked | Revisit fraction | Path efficiency | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | t5 | 5 | 75 | 0 | 0.00 | 1.00 | $0.013 |
| B | t75 | 58 | 22 | 0 | 0.45 | 0.48 | $0.032 |
| C | never | 75 | 5 | 0 | 0.64 | — | $0.034 |

Replay verification matched all 80 ticks. Total cost was $0.078; caching served 57–76% of input tokens.

**No blocked moves this time.** The first pilot had 8 moves into visible walls. Prompt v2 moved the current
observation into its own final block, after the notebooks. It's plausible that this stops agents copying stale
notes over what they can see, but with one run each this is only a hypothesis to test.

**Straight-line distance was the main trap.** Both agents treated `exit_distance_tenths` as a gradient to
descend. In a perfect maze the straight-line minimum is often a dead end:
- **B** reached junction (5,8) at t27, 13 steps from the exit. Its west branch was the way out, but the
  straight-line reading there was 5.4, worse than the 5.0 cell two steps south. B shuttled up and down that N–S
  corridor and parked on the 5.0 cell. It wrote "cells alternate 5.0/5.1 so exit is not straight along it" but
  never tried the 5.4 junction's west edge. It took that edge on its fifth visit, at t57, and reached the exit
  at t75.
- **C** ended on a cell 2.2 cells from the exit in a straight line but **39 moves away by path**. It wrote:
  "N and E both raise exit dist, so this is a local minimum. Staying put… Waiting for B to coordinate."
  Correctly diagnosed, then stuck.

**Bad advice from the agent at the exit.** A reached the exit in 5 moves and stayed there for the remaining 75
ticks as a "beacon". It radioed advice every 6 ticks:
- "Move toward decreasing exit_distance_tenths" (t36), reinforcing the gradient trap.
- At t42, "B: hold at 5.0 in the N-S corridor". B then spent 12 of its 22 STAYs parked there (t41–48,
  t51–54).

The beacon idea is also empty: once A stands on the exit, the peer range to A is the same number as the exit
distance. Neither agent remarked on this.

**C's loops were one dead-end subtree, walked three times.** C spawned 8.5 from the exit and first went east,
where the distance rose to 10.0, into a branch of about a dozen cells. It covered that branch at t3–12,
t28–41 and t44–50. C named cells by their exit distance ("the 7.3 cell", "the 8.1 cell"), a sensible
fingerprint that ties are rare here. But it described the branch as "loops", which a perfect maze cannot have.

At t44 it compacted 3,612 bytes of notes into 354, keeping only "Loops known… Unexplored: junction W branch
(t23) and far E", with the plan "explore E-side unexplored branches". That sent it around the branch a third
time. Only at t51 did it head west, after which it gained steadily (path distance 53 → 38 by t66) until the
local-minimum stall.

**A described its route relative to the outer wall.** A's first radio said "Route from spawn (outer brick is S
of spawn): N, N, W, S, W", trying to anchor the route to the boundary. B and C never used it; they were far
from that corner.

**Possible changes to test:**
- *(Done in prompt `maze_agent_v3`.)* Tell agents in the rules that straight-line distance ignores walls, so
  its local minima may be dead ends. The rules already said "not path lengths", but not what that implies.
- Add landmarks, so cells can be told apart by something other than distance.
- *(Done.)* Scale the horizon with maze size: 80 ticks is short for a 12×12 maze where one spawn is 52 moves
  out. An omitted `horizon_ticks` now defaults to 320 there, and run creation warns when a horizon is below the
  omniscient minimum.
- Record which junction edges have been tried, as the DFS baseline does. Neither LLM agent recorded this
  reliably.

## Third pilot: run `74ee0f522f1a`, same maze as the second, prompt v3
Same seed (202611017), 12×12 maze, spawns and 80-tick horizon as `6c7068296716`. The only change is the v3
rules sentence: because distance ignores walls, a cell where every move raises the reading can be a dead end.
Replay verification matched all 80 ticks. One run per prompt, so differences may be chance.

| Agent | v2 exit | v3 exit | v2 moves / stays | v3 moves / stays | v2 path efficiency | v3 path efficiency |
| --- | --- | --- | --- | --- | --- | --- |
| A | t5 | t5 | 5 / 75 | 5 / 75 | 1.00 | 1.00 |
| B | t75 | **t30** | 58 / 22 | 30 / 50 | 0.48 | **0.93** |
| C | never | never | 75 / 5 | 64 / 16 | — | — |

Total cost $0.078 (v2) vs $0.089 (v3). C's growing notebook accounts for most of the difference.

**B solved its maze, but not visibly because of the rule.** B's first 10 moves matched the v2 run. At t11 it
went W where v2-B had gone E, and at the (5,8) junction that trapped v2-B it tried W at once: "Trying W to test
whether it lowers distance". It did lower it (5.4 → 4.5), and B was on the exit by t30, two moves off the
shortest path. Its notes never cite the new sentence, and its stated reasoning is still "does this lower
distance?". So this may be luck as much as the rule.

**C went the right way at first, then stalled at the same dead end.**
- **Start:** unlike v2-C, it headed west at t2 and reached path distance 38 by t16, a point v2-C only reached
  at t66.
- **Stall:** it then spent most of the remaining 64 ticks around the (1,8) cell. That cell is 2.2 from the exit
  in a straight line but 39 moves away by path, the same trap as in v2. It reasoned "Both neighbors tested
  worse earlier (N 3.2, E 2.8). Holding STAY", and held there 11 times.
- **Turning back:** twice it set out east ("look for a southern route", t33–35; "probe the unexplored
  opening", t65–67). Each time it turned back after a step or two because the reading rose.

The rule sentence made C willing to test, but not to keep going while the distance rose.

**Peer advice cancelled out the new rule.** A and B, standing on the exit, broadcast 18 hints in total, most of
them greedy:
- "Move only when distance drops. Hold if stuck." (A, t65)
- "W and S lowered distance… avoid E." (B, t61, t67, t73, t79)

They turned the compass directions of their own successful routes into general advice for C, who was somewhere
else entirely, so "avoid E" was the opposite of what C needed. A even quoted the rule ("Exit reading is
straight-line only") in the same message as greedy advice. At t57 C was the one proposing the right strategy:
"Others, try unexplored far east or far north routes and report dist each step". No one did.

**Routes drift as they're retold.** A's notebook records its route correctly as N, N, W, S, W. Its radio told it
correctly at t11 and t29, then as "N, W, S, W (exit is 2 cells west of spawn)" from t47, dropping a step and
mis-stating the offset. At t79 B relayed that shortened version as "Route that worked for A and B", though B's
own route was quite different. The notebook was right; the retelling from memory was not.

**Sensor cross-checks, done right and wrong.**
- **C:** "My exit dist 3.2 equals my range to A, so A on exit is consistent". This correctly uses the peer
  range to verify A's claim to be on the exit.
- **B:** "A's radio says A is on exit but peer range shows A 5.4, so the readings conflict". This is wrong: B's
  own exit distance was 5.4, so a 5.4 range to A is exactly what being on the exit predicts.

**C's notebook nearly hit the cap.** It grew to 7,558 of 8,192 bytes with no compaction, and C's prompt tripled
from 1.9 k to 5.8 k input tokens. A slightly longer run would have produced its first `notebook_cap_exceeded`
rejections.

**Baseline reference on a different 12×12 maze** (run `2588cc541340`, seed 4224, horizon 200, oracle 57):
bounded DFS reached the exit at t167, the wall follower at t157, and random moves never did. The baselines need
roughly 3× the omniscient minimum on 12×12, so even the new 320-tick default is not generous for a weak policy.

**Next experiments suggested:**
- The rule moved behaviour less than the peers' advice did. Test an ablation with radio off on this maze: does C
  explore further when nobody tells it to "avoid E"?
- Several replicates per prompt version on this seed, before crediting B's improvement to v3.
- Landmarks would let C tell the (1,8) area apart and plan around it, rather than relying on distance alone.

## Fourth pilot: radio off, run `3cd5200d82ce` (same maze and prompt v3 as `74ee0f522f1a`)
Config: `configs/pilot_haiku_radio_off.json`. It is the v3 run's resolved config with only
`radio_enabled: false` and `radio_message_bytes: 0` changed. Same seed, maze hash, spawns, model and horizon.
Replay verification matched all 80 ticks, and no agent tried to transmit.

| Agent | Radio on: exit | Radio off: exit | Radio on: moves / stays | Radio off: moves / stays | Radio on: revisit | Radio off: revisit |
| --- | --- | --- | --- | --- | --- | --- |
| A | t5 | t5 | 5 / 75 | 5 / 75 | 0.00 | 0.00 |
| B | **t30** | **never** | 30 / 50 | 80 / 0 | 0.03 | 0.69 |
| C | never | never | 64 / 16 | 78 / 2 | 0.73 | 0.60 |

Team coverage was 64 cells with radio off against 48 with radio on. Cost was $0.064 against $0.089: no
messages, and A's notebook stayed at 359 bytes.

**Removing the greedy advice did not free the agents from greed.** The radio-on run suggested peer hints such as
"avoid E" were holding C back. Without them, both B and C still rejected moves because the distance reading rose:
- **B** reached (4,10), 8 steps from the exit, at t27. The way on was S, but its reading there was 4.0 against
  3.0 one cell back, so it wrote "dist 4.0 (up). Returning W to the dist 3.0 cell". In the radio-on run B took
  that same S step at t23 and finished at t30. The greedy habit comes from the model itself, not just from its
  peers.
- **C** explored a little further than with radio. It reached path distance 34 at t54, against 36 in the radio-on
  run, then turned back when the reading climbed to 5.7. The rule sentence (prompt v3) was present in both runs.

**B stopped taking notes, then swung back and forth for 38 ticks.** B made 31 notebook writes up to t42 and none
afterwards. Its last entry was "t42: at N/W open, E/S walls, dist 4.1. Trying N." From t40 to t80 it alternated
between (4,8) and (4,9) on almost every tick, about 18 round trips, with only short excursions. Each decision read
the stale last line, judged the direction it had just come from as "unexplored", and went back. With nothing
written about what had just happened, it lost even that one step of memory.

This is a sharper version of the first pilot's copy-forward failure. There the notes overrode what the agent
could see; here the notes stopped, and the agent had nothing to break the loop. A notebook-churn metric would
flag it: a long run of ticks with no writes while the agent keeps moving.

**C swung between two goals.** From t64 to t80 C walked (1,8) → (3,8) → (1,8), the same three cells, five times.
On the way east its notes said "probe the unexplored 4.2 east exit"; on the way back, "Moving W toward 2.2 area".
The low-distance cell kept pulling it back before the probe went anywhere.

**First moves vary between runs on the same prompt.** This run's C went E on its first move, into the same
dead-end branch v2-C wasted 50 ticks in. It left after 25 ticks this time. The radio-on v3-C went W at t2. With
identical inputs, Haiku's first move differs from run to run, so single runs per condition can't separate a
condition's effect from these early random choices.

**What these three runs on this maze suggest:**
- **The dominant failure is greedy distance-following.** It survives a rules sentence warning about it and the
  removal of peer advice that encouraged it.
- **Radio helped B here, probably by chance:** the radio-on B took the right step at the same decision point.
  Radio clearly cost money and produced much repeated advice. Telling chance from effect needs replicates.
- **Notebook discipline matters as much as strategy.** Agents that stop writing, or write stale lines, lose the
  little state that keeps them from looping.

**Next:** the phase 6 batch runner, to run about 5 replicates per condition on this seed plus a few other seeds,
before changing prompts again. Landmarks are the most promising structural fix for the local-minimum trap.

## Batch: radio ablation, 18 runs (`experiments/radio_ablation_v3.json`)
Conditions `radio_on` and `radio_off` (prompt v3, Haiku 5.5, 12×12, 80 ticks) × seeds 202611017, 101 and 102 ×
3 replicates. All 18 runs were valid. Full table: `reports/radio_ablation_v3.md`, from
`maze-lab report radio_ablation_v3 --baseline radio_on`. Intervals are 95% bootstrap resampled over the 3 seeds,
so they are wide and crude. Cost $1.41 for 4,320 decisions; about 30 minutes at 3 runs in parallel.

| Measure (per run) | radio_on | radio_off | off − on, paired by seed |
| --- | --- | --- | --- |
| Team success | 0 / 9 | 0 / 9 | 0 |
| Agents reaching the exit | 0.89 | 1.11 | +0.22 [−0.67, 0.67] |
| Coverage | 0.45 | 0.50 | +0.05 [−0.08, 0.12] |
| Path efficiency (agents that exited) | 0.92 | 0.88 | −0.04 [−0.18, 0.13] |
| Cost | $0.085 | $0.072 | **−$0.013 [−0.017, −0.010]** |

**Agents mostly got stuck; they didn't run out of time.** I first called this a floor effect from the
80-tick horizon. That was wrong. Across the 36 agents that never reached the exit:
- **They stopped improving early.** Path distance to the exit last improved at a median of t24, and for 26 of
  36 agents before t40.
- **They stopped finding new ground.** 22 of 36 visited no new cell in the final 20 ticks, and the median agent
  saw only 30 of 144 cells.
- **They drifted back.** The median agent ended further from the exit (30 moves) than its best (25).
- **Few were still progressing at the end:** only 5 agents were still getting closer in the last few ticks.

So a longer horizon would mostly have bought more looping. It would only matter once agents explore
systematically: the bounded-DFS baselines need about 170–200 ticks on 12×12, so 80 would also cap good
exploration. Success is zero here mainly because of stalling, not the clock.

**Distance from the exit decides who gets out.** Agents whose spawn was at most 25 moves from the exit reached it
in 11 of 12 cases. Agents 27 or more moves away managed 7 of 42. The one near-miss: seed 202611017, `radio_on`
replicate 2, agent A spawned 5 moves out. It went E first while the reading rose, wandered, and then sat on a
cell 2.0 from the exit in a straight line and 4 moves away by path, from about t40 to t80. This is the same
local-minimum trap as before, with the v3 rule present.

**Radio made no detectable difference to outcomes, but it changed behaviour.**
- **Outcomes:** every outcome interval spans zero. With 3 seeds a moderate effect can't be ruled out either way.
- **Waiting:** with radio on, agents that never reached the exit stood still far more. They averaged 21, 14
  and 42 STAYs per seed, against 6, 3 and 16 with radio off; the paired difference is −17 [−26, −11] stays per
  agent. Holding position "to coordinate" spends turns that could go on exploring, and the extra coordination
  bought no measurable progress.
- **Cost:** 296 messages in 9 runs, about 33 per run, at roughly 15% extra cost.

**Some single-run anomalies didn't generalise.**
- **Note-taking lapses were rare.** B's no-notes back-and-forth from the radio-off pilot showed up in only 2
  of 27 radio-off agents, and in no radio-on agent: a run of 10 or more moving ticks without a notebook write.
- **Walking into visible walls is now rare:** 2 blocked moves in 4,320 decisions, all with radio on. The v1
  pilot had 8 in 240. This fits the v2/v3 prompt layout, which puts the current observation in its own final
  block, but it hasn't been tested as a controlled comparison.
- **Greedy reversals and back-and-forth are routine and equal across conditions.** A greedy reversal is a
  move that raised the distance reading, undone on the next move; agents averaged about 3. A back-and-forth
  is returning to the cell of two moves ago; they averaged about 4.5.

**Hidden thinking can use up the output budget.** The single failed decision had `output_tokens` at the
2,048-token cap but only 127 characters of visible output: a JSON object cut off mid-string. Haiku 5.5 thinks
by default and the provider doesn't report thinking tokens separately, so this showed up as a schema failure.
The adapter now records it as "output truncated at max_tokens". It happened once in 4,320 decisions; raising
`max_output_tokens` would remove it, at some cost.

**Next:**
1. Work on stalling before spending on longer runs:
   - landmarks, so agents can tell cells apart;
   - a rules nudge to record which exits of a junction have been tried, as the DFS baseline does.
2. Track "STAYs before reaching the exit" and "ticks since the last new cell" as standard metrics; they move
   more than the outcome measures do.
3. A longer horizon (the 320-tick default) is worth testing once agents explore systematically. As things
   stand, it would mostly measure longer loops.

## Batch: junction-tracking nudge, v3 vs v4, 12 runs (`experiments/junction_nudge_v4.json`)
Prompt v4 adds one sentence to the rules: "note each junction you reach… and which of its exits you have
already tried, and prefer an untried exit when you come back". The conditions differ only in
`prompt_version`.

Same 12×12 maze, 80 ticks, radio on and Haiku 5.5 as the radio ablation. Seeds 202611017, 101 and 102 × 2
replicates; all 12 runs valid. Full table: `reports/junction_nudge_v4.md`. Intervals are 95% bootstrap
resampled over 3 seeds, so they are wide.

| Measure (per run) | v3 | v4 | v4 − v3, paired by seed |
| --- | --- | --- | --- |
| Coverage | 0.45 | 0.55 | **+0.095 [0.035, 0.177]** |
| Revisit fraction | 0.43 | 0.36 | **−0.068 [−0.108, −0.038]** |
| STAYs before exiting (team) | 40.8 | 24.5 | **−16 [−28, −6]** |
| Progress to exit (best fraction of path closed) | 0.585 | 0.597 | +0.012 [−0.022, 0.044] |
| Agents reaching the exit | 0.83 | 1.00 | +0.17 [−0.5, 0.5] |
| Ticks since last new cell (agents that never exited) | 19 | 32 | +13 [−4, 26] |
| Team success | 0 / 6 | 0 / 6 | 0 |
| Cost | $0.085 | $0.087 | +$0.002 |

**Agents adopted the habit almost universally.**
- **Tried exits:** 17 of 18 v4 agents' final notebooks record tried or untried exits, against 1 of 18 under v3.
- **Junctions:** 16 of 18 mention junctions, against 8 of 18.
- **Invented cell IDs:** several v4 agents began numbering cells to tell them apart, which nobody had done
  before. One wrote: "T4 at cell4 (E of cell3): open N,S,W… Trying N first; S untried… heading back S to
  cell4 to try its untried S exit".

**It changed how agents explore, but not how close they get.** v4 agents covered more of the maze, revisited
less and waited less; all three intervals exclude zero. But their best progress toward the exit was unchanged,
and still no team finished in 80 ticks.

The stall measure points the other way: agents that never exited had gone longer without finding a new cell
(32 vs 19 ticks; the interval includes zero). One reading is that the habit spreads exploration early, but once
a region's junctions are all marked tried, agents still have no way to choose where to go next. The local
straight-line pull then takes over again. That fits the earlier single runs, where the stalls happened next to
low-distance cells.

**Costs are unchanged.** Notes are a little longer, but caching absorbs most of it. One decision in 2,880
was again cut off by hidden thinking hitting the 2,048-token output cap; it was recorded correctly as "output
truncated at max_tokens".

**What this suggests:** the notebook habit is cheap and the model follows it, so prompt-level strategy hints
do change behaviour. Better exploration alone doesn't get agents out, though. The bottleneck is choosing which
untried exit leads anywhere, and the straight-line reading is a poor guide for that. Landmarks, which give
agents fixed reference points, are the next lever to test. The stall measure should also be tracked per tick,
not only at the end.

## Batch: landmarks, v4 vs v4 + 10 landmarks, 12 runs (`experiments/landmarks_v4.json`)
Ten landmarks (unique labels such as "mirror" and "cactus") on random cells of the same 12×12 mazes; only
`maze.landmark_count` differs. Prompt v4, 80 ticks, radio on, Haiku 5.5, seeds 202611017, 101 and 102 × 2
replicates. Full table: `reports/landmarks_v4.md`. Intervals are 95% bootstrap over 3 seeds.

| Measure (per run) | v4 | v4 + landmarks | Landmarks − v4, paired by seed |
| --- | --- | --- | --- |
| Progress to exit (best fraction of path closed) | 0.672 | 0.737 | **+0.065 [0.027, 0.106]** |
| Agents reaching the exit | 1.17 | 1.00 | −0.17 [−0.5, 0] |
| Coverage | 0.55 | 0.59 | +0.045 [−0.04, 0.14] |
| Revisit fraction | 0.35 | 0.32 | −0.02 [−0.05, 0.03] |
| STAYs before exiting (team) | 0.3 | 12.5 | +12 [−0.5, 37] |
| Ticks since last new cell (agents that never exited) | 8 | 15 | +7 [−5, 20] |
| Team success | 0 / 6 | 0 / 6 | 0 |
| Cost | $0.085 | $0.090 | +$0.005 [−0.002, 0.010] |

**Agents got closer, but not out.** With landmarks they closed about 6.5 percentage points more of their path to
the exit at their best, an interval that excludes zero. No more of them actually reached it, and no team
finished in 80 ticks. The other differences are within noise at n = 3 seeds.

**Landmarks became place names, combined with the junction habit.**
- **Seen and kept:** 13 of 18 agents stood on at least one landmark, and 10 of them still had it in their final
  notebook.
- **Used as cell names:** "T48: at guitar cell (open S,W; walls N,E)". This replaces the distance-based names
  from earlier runs, such as "the 7.3 cell".
- **The clearest use**, by agent C in `77f80e3a3946`: "North corridor above mirror is exhausted (dead ends).
  Next: cell south of mirror (N,E,S open) has untried E". That is the v4 junction habit anchored to a landmark,
  exactly the combination hoped for.

**They rarely shared landmarks.** Only 10 of 155 radio messages named one. Agent A did ask peers to "post your
landmarks and exit distances", but the replies garbled it: B wrote "Peer A's clock/basket hints noted" when
A had said cactus and basket. That is the same retelling drift seen with routes.

**Viewer:** landmarks are drawn as small labels (◆ tree) and included in each cell's screen-reader label.

**Process note:** I accidentally ran this batch twice at once. The coordinators' fencing kept the data
intact, but 4 cells ended up as excluded recovered runs. Batches now give each cell a deterministic run id,
so duplicate invocations converge on the same run, and `--rerun-invalid` replaced those cells. The numbers
above come from the final 12 valid runs.

**Overall pattern across the last three batches:**
- **What worked:** prompt-level habits (v4) and landmarks both moved exploration in the intended direction,
  cheaply.
- **What didn't move:** whether agents actually reached the exit within 80 ticks.
- **Where the bottleneck is:** choosing which untried branch to take, and then committing to it while the
  straight-line reading gets worse.

Two next steps would show whether these gains turn into exits: a longer horizon (320 ticks) now that
exploration is more systematic, and a stronger model on the same specs.

## Single run: Sonnet 5.5 on v4 + landmarks, run `ac57358e8053` (`configs/sonnet55_v4_landmarks.json`)
This is the config of the Haiku `landmarks_v4` / `v4_landmarks` runs on seed 202611017 with only `model`
changed to `claude-sonnet-5-5`: same 12×12 maze, 10 landmarks, prompt v4, 80 ticks, radio on and a
2,048-token output cap. It is compared with the two Haiku runs of that cell (`c5c295d66542`,
`d80ae20b7b8e`). **One run against two**, so treat it as a strong anecdote, not an estimate. Replay
verification matched all 70 ticks.

| | Haiku r0 | Haiku r1 | **Sonnet** |
| --- | --- | --- | --- |
| Team objective | not met | not met | **met at t70** |
| A (spawn 5 moves out) | exit t5 | exit t5 | exit t5 |
| B (spawn 28) | exit t32 | never (got within 20) | exit t30 |
| C (spawn 52) | never (got within 32) | never (got within 20) | **exit t70**, 70 moves, 0 stays, revisit 0.14 |
| Cost | $0.073 | $0.086 | **$1.757** (~22×) |
| Output tokens per decision (median) | 312 | 386 | 229 |
| Latency p50 / p90 | 2.3 / 4.1 s | 2.6 / 4.0 s | 3.2 / 6.2 s |
| Cache reads as share of input | 73% | 62% | 42% |
| Failed or truncated decisions | 0 | 0 | 0 |

This is the first LLM team to meet the objective in any run so far. It came from three things Haiku never
combined.

**1. A coordinate frame anchored on a landmark.**
- **The anchor:** Sonnet's C labelled the fountain cell "W10" and made it the origin. It tracked relative
  coordinates from there ("E13=(3,1)"), something no Haiku agent did in any run.
- **Locating the exit by distance:** it estimated the exit's position from its distance readings and kept
  checking the estimate: "t25: at (3,-2) dist 5.8 matches exit (0,3) rel W10". So the straight-line reading
  became a sensor for locating the exit, not a gradient to follow.

**2. Willingness to move away from the exit.** With a position estimate, C could accept a rising reading as part
of a detour. At t18 it wrote "dist 3.6 rising… Only new exit N, going N". At t40 it went east to "look for a
southern route" at distance 7.8. Haiku agents in the same spot turned back to the low-distance cell and
stalled.

**3. Routes anchored on landmarks, shared over the radio.**
- **The request:** at t48 C asked "Please give turn-by-turn route from the fountain or ladder landmark".
- **The answer:** at t49 B replied with "B route to exit from PICTURE cell (S brick, W wall, N/E open):
  N,N,N,W,S,W,S,E,S,W,W,N,N,W,S,W".
- **Following it:** C found the picture cell at t55 and followed the 16 steps, logging its progress ("Route
  steps 1-10 done… Step11 W"), and reached the exit at t70.

This is the cooperation the experiment is designed to detect. It needed landmarks: a route from someone's
spawn, as in the Haiku runs, is useless to anyone else.

Peer advice was also more nuanced, though still partly greedy: "Follow falling distance, accept small rises";
"if distance rises over several steps, backtrack and try an untried junction exit".

**Cost.** Sonnet used fewer output tokens than Haiku and similar input, but costs about 20× per token: $1.76
for the game, against about $0.08. Its cache share was lower (42%) because its notebooks changed every tick
and were re-written to the cache. It never came near the 2,048-token cap; the largest output was 1,345.

**Next:** a small Sonnet batch (`landmarks_v4` with the model swapped, 3 seeds × 1 replicate, about $5) to see
whether this holds beyond one seed and one run. Sonnet with landmarks off would isolate how much of the gain is
the model and how much is landmarks.

## Batch: Sonnet 5.5, landmarks on and off, 6 runs (`experiments/landmarks_v4_sonnet.json`)
The configs are identical to the Haiku `landmarks_v4` batch except `model: claude-sonnet-5-5`: same seeds
(202611017, 101, 102), 12×12 maze, prompt v4, 80 ticks, radio on, 2,048-token output cap. There is 1
replicate per cell. Full table: `reports/landmarks_v4_sonnet.md`. The Haiku comparison is across two
experiments, but configs and seeds match.

| Per run | Haiku v4 | Haiku v4 + landmarks | Sonnet v4 | Sonnet v4 + landmarks |
| --- | --- | --- | --- | --- |
| Team success | 0 / 6 | 0 / 6 | **2 / 3** (t68, t71) | **1 / 3** (t73) |
| Agents reaching the exit (of 3) | 1.17 | 1.00 | 2.67 | 2.33 |
| Progress to exit (best fraction of path closed) | 0.67 | 0.74 | 0.98 | 0.90 |
| Revisit fraction | 0.35 | 0.32 | 0.14 | 0.21 |
| STAYs before exiting (team) | 0.3 | 12.5 | 0 | 0 |
| Cost | $0.085 | $0.090 | $1.36 | $1.62 |

**The model is the big lever; landmarks were not essential.**
- **Sonnet without landmarks** met the objective in 2 of 3 runs, more than with them (1 of 3). The difference
  is within noise at this n.
- **The single Sonnet run's win** relied on a route anchored on a landmark, but Sonnet succeeds by other routes
  too.
- **The same cell can go either way:** the batch's own run of seed 202611017 with landmarks (`73b66b4e6638`)
  hit the tick limit, while the earlier single run on that cell (`ac57358e8053`) succeeded.

**How Sonnet differs, per agent:**

| Habit | Haiku | Sonnet |
| --- | --- | --- |
| Greedy reversals (a move that raised the reading, undone at once) | 2.3 | **1.4** |
| Back-and-forth moves (returning to the cell of two moves ago) | 4.3 | **1.8** |
| Keeps coordinates (notebook has (x, y) pairs) | 0–6% of agents | 22–33% |
| Estimates the exit's position | 0% | 22–33% |
| Routes shared from a landmark (radio, with landmarks on) | 0.11 per agent | **1.67 per agent** |
| Share of moves that raised the straight-line reading | 0.41 | 0.38 |
| Median output tokens per decision | 386 | **225** |

The difference is not more willingness to walk away from the exit: both models raised the reading on about 40%
of their moves. Sonnet's moves were decisive: fewer reversals, far fewer back-and-forth moves, no waiting,
and less text. Only a minority of Sonnet agents kept explicit coordinates, so coordinates aren't required
either; most Sonnet agents just explored without dithering. When landmarks existed, Sonnet used them to share
routes about 15× more often than Haiku.

**Cost and reliability.** About $1.36–1.62 per run, against $0.09 for Haiku: 16–18× per run, roughly $3 per
team success. Two Sonnet decisions in 1,440 were cut off at the 2,048-token cap, both from one agent on
consecutive turns, presumably hidden thinking at Sonnet's default "high" effort. Haiku had one in 2,880.

## Batch: can Haiku be pushed into Sonnet's habits? 24 runs (`experiments/haiku_pattern.json`)
All runs use Haiku 5.5, 10 landmarks, 12×12, 80 ticks and radio on, on seeds 202611017, 101 and 102 × 2
replicates. The four conditions are:
- **v4:** the baseline.
- **v5:** v4 plus the habits that won the Sonnet run, stated generally: keep your own coordinates from a chosen
  origin; read the exit distance at known positions to estimate where the exit is, and plan toward it even when
  a route first leads away; start shared routes from a landmark.
- **v4_high / v5_high:** the same prompts with Anthropic `effort: high`. The default for Haiku 5.5 is medium.

All 24 runs were valid. Full table: `reports/haiku_pattern.md`.

| Per run | v4 | v5 | v4 + high effort | v5 + high effort |
| --- | --- | --- | --- | --- |
| Team success | 0 / 6 | 0 / 6 | **1 / 6** (t68) | **1 / 6** (t61) |
| Agents reaching the exit (of 3) | 1.17 | 1.00 | 1.67 | 1.67 |
| Progress to exit, difference from v4 | — | **−0.10 [−0.21, −0.05]** | +0.06 [−0.11, 0.15] | 0.00 [−0.07, 0.04] |
| Agents keeping coordinates | 0% | **100%** | 6% | **100%** |
| Agents estimating the exit's position | 0% | 83% | 6% | 94% |
| Noted positions matching true offset from start | — | 28% | — | 42% |
| Forced STAYs (truncations) per run | 0 | 0.5 | **5.7** | **12.3** |
| Median output tokens per decision | 373 | 378 | 508 | 545 |
| Cost | $0.083 | $0.083 | $0.117 | $0.130 |

Both successes were on seed 102, the easiest maze: the slowest spawn needs 33 moves.

**Context alone got compliance, not competence.**
- **Full uptake:** every v5 agent kept coordinates, and most estimated the exit's position.
- **Correct estimates:** some estimates were right. B in `14127c448543` wrote "Triangulated exit from readings
  at (0,0),(0,-3),(-1,-3),(1,-3): approx (-6,2)", and that was exactly right in its frame.
- **Drifting positions:** the bookkeeping failed. Agents updated coordinates for the move they were about to
  make, or forgot the last one. Positions slipped one step behind within a few ticks (B: "t8: at (-1,-3)" when
  it was at (-2,-3)), and only 28% of noted positions were correct.
- **Distrust, then abandonment:** the agents then noticed contradictions and stopped trusting their maps.
  "Coords may be off… Trusting A's…"; "Coords still unreliable"; "my coords may be off by one".
- **Frame confusion:** C took B's exit estimate, which was in B's frame, and steered toward "(-6,2)" in its own
  frame, a different place.
- **Net effect:** progress toward the exit was worse than v4.

**More thinking is what helped.**
- **Results:** high effort produced Haiku's only team successes, half an extra agent at the exit per run, and,
  with v5, more accurate coordinates (42%).
- **The cost:** thinking now regularly hit the 2,048-token output cap. 34 (v4) and 74 (v5) decisions were cut
  off and became forced STAYs, so the gain is understated. Cost rose 40–57%, still about a tenth of Sonnet's.

**Implication.** The spec forbids the engine from keeping an agent's map for it (§4.2), so dead reckoning has to
stay the agent's job. The next test is cheap: high effort with a larger output cap (say 8,192), to see how much
of the gap closes once thinking isn't cut off. If it closes most of it, the story is less "Haiku can't" than
"Haiku needs room to think, and the default budget hides that".

## Batch: high effort with an 8,192-token cap, 12 runs (`experiments/haiku_high_8k.json`)
These are the `haiku_pattern` high-effort conditions (v4 and v5, `effort: high`, 10 landmarks, 12×12, 80 ticks,
same seeds and replicates), with `max_output_tokens` raised from 2,048 to 8,192 so thinking is no longer cut
off. Full table: `reports/haiku_high_8k.md`. The table below sets every condition on these seeds side by side;
the rows come from different experiments, but configs match apart from the stated change.

| Condition | Team success | Agents exited | Progress | Forced STAYs per run | Output tokens per decision (median / p90 / max) | Latency p50 / p90 | Coordinates correct | Cost per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku v4, medium effort, 2k cap | 0 / 6 | 1.17 | 0.73 | 0.0 | 373 / 600 / 1,501 | 2.6 / 3.9 s | — | $0.083 |
| Haiku v5, medium, 2k | 0 / 6 | 1.00 | 0.63 | 0.5 | 379 / 684 / 2,048 | 2.6 / 4.2 s | 28% | $0.083 |
| Haiku v4, high, 2k | 1 / 6 | 1.67 | 0.79 | 5.7 | 516 / 1,013 / 2,048 | 3.3 / 5.9 s | — | $0.117 |
| Haiku v5, high, 2k | 1 / 6 | 1.67 | 0.73 | 12.3 | 560 / 1,446 / 2,048 | 3.5 / 7.8 s | 42% | $0.130 |
| **Haiku v4, high, 8k** | **0 / 6** | 1.17 | 0.68 | 0.5 | 545 / 1,206 / 8,192 | 3.3 / 6.5 s | — | $0.140 |
| **Haiku v5, high, 8k** | **0 / 6** | 1.67 | 0.75 | 0.2 | 553 / 1,312 / 8,192 | 3.3 / 6.9 s | 46% | $0.132 |
| Sonnet v4 + landmarks, default effort, 2k | 1 / 3 | 2.33 | 0.90 | 0.7 | 221 / 432 / 2,048 | 3.0 / 4.8 s | (origin at a landmark) | $1.62 |
| Sonnet v4, no landmarks | 2 / 3 | 2.67 | 0.98 | 0.0 | 227 / 414 / 1,516 | 3.0 / 4.6 s | 98% | $1.36 |

"Coordinates correct" is the share of noted (x, y) positions that match the true offset from the agent's start.
It is meaningless for agents that put the origin at a landmark, as the successful Sonnet runs often did.

**Removing the cap removed the truncations, not the gap.** Forced STAYs fell to under one per run, but no
8k-cap run met the objective, and exits and progress matched default-effort Haiku. The two 2k-cap high-effort
successes were both on seed 102, the easiest maze. With no successes at 8k, they look like luck.

**Haiku thinks more and does worse.** At high effort Haiku produced about 2.4× Sonnet's output per decision and
still kept coordinates less than half right. Sonnet answered in about 225 tokens and, when tracking from its
start, kept them about 98% right. Extra reasoning budget doesn't substitute for the stronger model's precision.

**Cost per success.** Haiku spent $7.59 across all 78 batch runs on this setup for 2 team successes, about $3.80
each. Sonnet spent $8.93 on 6 batch runs for 3, about $3.00 each. Despite costing ~16× more per run, the
stronger model is the cheaper way to get a team out. These figures exclude the re-run cells and the duplicate
runs from the accidental double batch.

## DeepSeek v4.1 Flash via OpenRouter, 2k and 8k caps (`experiments/landmarks_v4_deepseek*.json`)
Model `deepseek/deepseek-v4.1-flash-1017` through OpenRouter on the same cells as the Haiku and Sonnet landmark
runs: plain v4 + 10 landmarks, 12×12, 80 ticks, barrier timing with a 60 s ceiling, seeds 202611017, 101 and
102 × 1. The settings differ from the Anthropic runs in two ways:
- **Output mode is `tool`:** PydanticAI's profile says native structured output isn't supported for this model.
- **Costs are OpenRouter's billed amounts** (usage accounting), not estimates. Prices are $0.15 / $0.60 per
  million input / output tokens, $0.003 per million for cached input, doubling at some weekday hours. These
  runs were on a Saturday.

Full tables: `reports/landmarks_v4_deepseek.md` (2k) and `reports/landmarks_v4_deepseek_8k.md` (8k).

| Same cells (v4 + landmarks) | Team success | Agents exited | Progress | Forced STAYs (cause) | Output tokens per decision | Latency p50 / p90 | Cost per run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku, medium effort, 2k (6 runs) | 0 / 6 | 1.00 | 0.74 | ~0 | 401 | 2.7 / 4.0 s | $0.09 |
| Haiku, high effort, 8k (6 runs) | 0 / 6 | 1.17 | 0.68 | ~0.5 | 545 | 3.3 / 6.5 s | $0.14 |
| Sonnet, default effort, 2k (3 runs) | 1 / 3 | 2.33 | 0.90 | ~0.7 | 221 | 3.0 / 4.8 s | $1.62 |
| DeepSeek, 2k (3 runs) | 0 / 3 | 0.67 | 0.50 | 406 of 720 decisions (cut off) | 2,048 (the cap) | 14.3 / 20.7 s | $0.23 |
| DeepSeek, 8k (3 runs) | 0 / 3 | 1.33 | 0.68 | **~61 per run** (137 timeouts, 43 cut off, 2 schema failures) | 1,789 (1,506 reasoning) | 16.1 / **49.8 s** | $0.30 |

**At a 2k cap, the cap is all you measure.** DeepSeek reasons at length (median ~1,500 reasoning tokens per
decision at 8k), so at 2,048 tokens 56% of decisions were cut off. Each cut-off answer is still billed in full,
so the 2k runs cost more than the smoke test suggested ($0.23 against ~$0.04 per run). Any comparison with
reasoning models needs a cap well above their typical reasoning length.

**At 8k, the clock is the limit.** With room to reason, decisions took 16 s at the median and 50 s at the 90th
percentile. Under barrier timing every tick waits for the slowest agent, up to the 60 s ceiling, after which an
unanswered agent is forced to STAY. 137 decisions timed out, 43 were still cut off even at 8k, and 2 failed the
schema: 182 of 720 turns lost, about 25%. (An earlier version of this note double-counted the timeouts as 274
and ~44%.) Outcomes (1.33 agents exited, progress 0.68) landed at Haiku's level, but with a quarter of turns
forfeited that says little about the model.

**The habits are there without prompting.** Under plain v4, which only asks for junction notes:
- **Coordinates and exit estimates:** all 9 DeepSeek agents kept coordinates and estimated the exit's
  position. Haiku needed v5 to do either, and only 22–33% of Sonnet agents did.
- **Landmark routes:** it shared routes anchored on landmarks 1.1 times per agent, against Sonnet's 1.7 and
  Haiku's 0.1.
- **Distance reasoning:** an example note: "T2… exitD=92 (spawn was 85) => distance rose moving E, so exit
  lies WEST. Returning W", followed by a structured coordinate log per cell ("(-1,0) d78: N open…").
- **Accuracy is uncertain.** The coordinate-accuracy heuristic gives ~30%, but DeepSeek notes list many cells
  per line, so a first-match check is unreliable here. Treat that figure loosely.

**Cost.** $0.30 per run at 8k, about 2× Haiku at high effort and a fifth of Sonnet, almost all of it output and
reasoning tokens. Automatic prefix caching worked through OpenRouter (cache reads on most calls).

**Next, for a fair comparison:** rerun at 8k with a much longer barrier ceiling, say 180–300 s, so slow
reasoning isn't scored as forfeits. This costs nothing extra in tokens but takes much longer: probably 1–2 hours
for 3 runs. The same applies to local models, whose throughput will also decide how many turns they lose.

## DeepSeek v4.1 Flash rerun with a 600 s decision window (`experiments/landmarks_v4_deepseek_8k_w600.json`)
Identical to the 8k DeepSeek batch except the barrier ceiling: 600 s instead of 60 s. Barrier timing waits
only as long as the slowest agent needs, so the bigger window costs nothing unless a decision is slow. Full
table: `reports/landmarks_v4_deepseek_8k_w600.md`.

| DeepSeek v4.1 Flash, 8k cap | Team success | Agents exited | Progress | Turns lost | Latency p50 / p90 / max | Wall time per game | Cost per run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 60 s window | 0 / 3 | 1.33 | 0.68 | 182 of 720 (137 timeouts, 43 truncated, 2 schema) | 16 / 50 / 60 s (capped) | 59 min | $0.30 |
| **600 s window** | **1 / 3** (seed 102, **t53**) | 1.67 | 0.74 | 96 of 639 (0 timeouts, 90 truncated, 6 schema) | 10 / 40 / 86 s | 33 min | $0.38 |

- **The window was the main handicap.** With no timeouts, DeepSeek met the team objective on seed 102 at t53.
  That beats Sonnet's best (t68), on the easiest of the three mazes. Its slowest decision took 86 s, so the
  60 s window had been cutting off its longest thinking.
- **Timeouts made the games slower, not faster.** Games ended up quicker in wall time (33 vs 59 min per game),
  because under the 60 s window every timed-out tick waited the full 60 s.
- **The 8k cap still bites.** 90 decisions (14%) hit 8,192 output tokens, and each cut-off answer is billed in
  full. A 16k cap would probably remove most of these, at a little more cost per long decision.
- **The habits held.** Again unprompted, all 9 agents kept coordinates and estimated the exit's position, and
  shared landmark routes 0.8 times per agent.
- **The picture so far, n = 3:** with enough time to think, a cheap open-weight reasoning model ($0.38 per run)
  lands between Haiku and Sonnet. Sonnet costs ~4× more per run and still does better on average (2.33 agents
  exited against 1.67).

## Local: Qwen3.5-9B (Unsloth IQ4) on Ollama, 3 runs (`experiments/landmarks_v4_qwen35_9b.json`)
Same cells as the Haiku, Sonnet and DeepSeek landmark runs: v4 + 10 landmarks, 12×12, 80 ticks, seeds 202611017,
101 and 102. Settings for the local model:
- **Context:** Ollama runs it with an 8,192-token context (server-side).
- **Reasoning off:** `effort: "none"`, sent as `reasoning_effort: "none"`. Its thinking is on by default; a
  one-word reply took 122 reasoning tokens.
- **Output:** native structured output. Tool mode failed, because Qwen left required fields out of the tool
  arguments.
- **Limits:** 1,024-token output cap; barrier ceiling 180 s, because 3 games × 3 agents share one GPU.

**Fitting 8k.**
- **Tokenizer:** Qwen's tokenizer is denser on our prompts, at 3.1–3.8 bytes per token measured on recorded
  prompts (Haiku: 1.7–1.9). The config uses `context_bytes_per_token: 3.0`.
- **Meeting notebooks off:** even so, three full 8 KB notebooks (own plus two co-located) don't fit, so meeting
  notebooks are off; the worst case is then 5.6k input + 1k output.
- **Why that's harmless here:** in every earlier Haiku and Sonnet landmark run, the only agents who ever read
  a teammate's notebook had already reached the exit and were standing on it. Switching them off removes
  nothing that affected navigation.

Full table: `reports/landmarks_v4_qwen35_9b.md`.

| Same cells (v4 + landmarks) | Team success | Agents exited | Progress | Coverage | Revisit | Moves into visible walls | Back-and-forth per agent | Output tokens | Latency p50 | Cost per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku 5.5 (6 runs) | 0 / 6 | 1.00 | 0.74 | 0.59 | 0.32 | 0.1% of decisions | 4.2 | 401 | 2.7 s | $0.09 |
| Sonnet 5.5 (3 runs) | 1 / 3 | 2.33 | 0.90 | 0.62 | 0.21 | 0% | 1.8 | 221 | 3.0 s | $1.62 |
| DeepSeek v4.1 Flash, 8k (3 runs) | 0 / 3 | 1.33 | 0.68 | 0.53 | 0.49 | 0.3% | 3.9 | 1,789 | 16.1 s | $0.30 |
| **Qwen3.5-9B local (3 runs)** | **0 / 3** | **0.00** | **0.29** | 0.29 | 0.75 | **32.8%** | **14.1** | 99 | 25.3 s (queued) | $0 |

**Reliable infrastructure, unreliable perception.** The local setup itself worked: 4 failed decisions in 720
(all cut off at 1,024 tokens), no context overflows, no timeouts. The model's play was the problem.
- **Walls:** one decision in three walked into a wall that was visible in the same turn's observation.
- **Ignoring feedback:** 50 of those 236 blocked moves repeated the exact direction that had just been
  reported as blocked.
- **Miscopying the observation:** the notes show it copying the JSON edges wrongly. At t17 it received `E:
  interior_wall` and wrote "E-Open… Attempting E again". At t30 it received `W: outer_brick` and wrote
  "W-Open".
- **The result:** back-and-forth moves were 3–8× higher than any other model, only 29% of the maze was
  covered, and no agent reached the exit.

**What it did get.** It used the notebook every turn, kept short journals (median 99 output tokens per
decision), and 2 of 9 agents tried coordinates. It never estimated the exit's position, and never radioed a
landmark-anchored route.

**Interpretation.** For this 9B model at IQ4 with reasoning off, the first rung of the ladder (reading the
current observation correctly) isn't reliable, so none of the higher-level shepherding can matter yet. Worth
trying next, cheaply and locally:
- **Turn its reasoning back on,** with a larger output cap. It thinks by default, and the earlier models that
  did best all reasoned.
- **Simplify the observation:** a plainer edge format, or a prompt v6 that asks the agent to restate the four
  edges before choosing a move. That would be the first rung's shepherding, applied to a smaller model.

## Qwen3.5-9B follow-up: queuing, restating edges (prompt v6), field order, reasoning
Three questions after the first local batch. Was it the request queue? Would making the model restate its edges
help? What actually drives the wall-walking?

**Queuing is ruled out, both by measurement and by experiment.**
- **No prompt was cut off.** Ollama's reported prompt tokens track prompt size linearly (3.2–3.9 bytes per
  token) up to the largest prompt (~3.3k tokens, well inside the 8,192 context). `OLLAMA_NUM_PARALLEL=1`, so
  requests run one at a time and never share a context; queuing only adds waiting.
- **Running one game at a time didn't change the picture.** In `experiments/qwen35_9b_restate.json`, condition
  v4, latency fell from 25 s to 3.9 s per decision, but the results matched the queued batch: 28.5% of moves
  into walls (33% queued), no exits, progress 0.22.

**Prompt v6 (restate edges before choosing) didn't help.** v6 = v4 plus "start this turn's note by copying your
cell's four edges exactly… choose only a direction whose edge is open… do not repeat a blocked direction".
Results over 3 seeds, each run one game at a time:

| Qwen3.5-9B | Moves into walls | Repeated a just-blocked direction | Notes restating edges | Edges copied correctly (open vs closed) | Moves through an edge its own note called closed | Exits | Progress |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v4, queued (first batch) | 32.8% | 50 | 20% | 90% | 31 of 143 | 0 | 0.29 |
| v4, one game at a time | 28.5% | 35 | 26% | 87% | 43 of 187 | 0 | 0.22 |
| **v6 restate**, one at a time | 25.7% | 21 | 48% | **95%** | **77 of 346 (22%)** | 0 | 0.15 |

- **It was reading the edges correctly.** An earlier check said it miscopied them, but that check scored
  Qwen's "O" abbreviation for open as wrong. Corrected, Qwen copies edges right 87–95% of the time.
- **The failure is acting against its own notes.** In about one decision in five it moved through an edge it
  had just written down as closed. v6 doubled how often edges were restated and cut repeats of a just-blocked
  direction, but walls were still hit about a quarter of the time and no agent exited.

**Field order isn't the cause; reasoning is the lever.** Hypothesis: with reasoning off, the model writes the
JSON fields in schema order, and `move` comes before `notebook_edit`, so it commits to a move before restating
anything. To test it, I replayed 40 of the v6 decisions that went through a self-declared closed edge, with
the exact recorded prompts:

| Replay of 40 bad decisions | Moves into a closed edge | Valid move returned |
| --- | --- | --- |
| As run (move first, reasoning off) | 5 (12%) | 40 |
| Note field first, reasoning off | 9 (22%) | 40 |
| Move first, **reasoning on** (4,096-token cap) | **0 (0%)** | **18** |

- **Mostly random sampling error.** Replayed with identical inputs, only 12% of the bad decisions went wrong
  again. The wall-walking is sampling noise at a high base rate (Ollama's default temperature), not a fixed
  misreading of particular cells.
- **Field order: test invalid.** Putting the note first appeared not to help (22%). But a captured request
  (Vessel #5870) shows Ollama's structured output emitting keys in **alphabetical order** whatever the schema
  says: `move`, `notebook_edit`, `radio`, `schema_version`, `tick`, and inside the edit `end`,
  `expected_revision`, `start`, `text`. Reordering the schema therefore couldn't put the note first, so this
  replay didn't test the hypothesis. A real test needs the note under a key that sorts before `move`, or
  reasoning on.
- **Reasoning fixes the moves but often doesn't finish.** With thinking on, none of the 18 answers went into a
  wall. But 22 of 40 returned no parseable move within 4,096 tokens, presumably because thinking used up the
  budget; I didn't diagnose this further.

**One captured example** (Vessel #5870, run `dbef9cc1d9b9`, agent A, decision tick 74). The observation
said `north: interior_wall, east: interior_wall, south: open, west: outer_brick`. Qwen replied `move: "N"` with
the note "Walls: N-int, E-int, S-open, W-brick… Continuing N".
- **Plan inertia:** it named the wall correctly and still followed its previous note's plan ("Moving N to keep
  moving away…").
- **Its correction was lost:** the note's splice (start 2582, end 2583 on a 2,582-character notebook) was
  rejected as `invalid_span`.
- **A wasted broadcast:** it radioed "No change.".
- **A long-running mess:** earlier notebook lines were already out of order (ticks 28, 22, 21, 20, 23…) from
  wrong insert offsets, and tick 45 had recorded this same dead end.

**The 'null' radio quirk.** Under native structured output, Qwen often sent the radio field as the string
`"null"` instead of JSON null: 20–28 times per three-game batch. The engine accepts that as a real broadcast,
so teammates got "null" messages.

**Takeaways for a small local model:**
- **The cheap fixes don't move this failure.** It isn't perception or field order, so prompt shepherding at
  the perception rung (v6) doesn't reach it.
- **What does help is thinking time, then sampling.**
  - Reasoning on, with a big enough output cap. The 8k context leaves ~2.5k output tokens beside a worst-case
    prompt, so the notebook cap would need shrinking.
  - Lower sampling temperature with reasoning off. Tested below: it cuts wall moves about threefold.

**Temperature replay (reasoning off, recorded v6 prompts replayed through Vessel, session `temperature-replay`).**
Two sets from the v6 batch: 60 random decisions, and the 40 that went through an edge the agent's own note
called closed.

| Temperature | Random decisions: moves into walls | The 40 bad decisions: moves into walls | Unparseable replies (random set) |
| --- | --- | --- | --- |
| Ollama default (as run) | 14 of 58 (24%) | 32 of 119 (27%), 3 samples each | 1 |
| 0.2 | **5 of 56 (9%)** | 16 of 120 (13%), 3 samples each | 4 |
| 0 (greedy) | **4 of 58 (7%)** | 8 of 40 (20%), 1 sample | 2 |

- **Most wall-walking is sampling noise.** On random decisions the rate fell from 24% to 7–9%, close to a
  third.
- **A hard core remains.** About 8 of the 40 bad decisions go into the wall even greedily. That's the plan
  inertia seen in Vessel #5870: the model's top choice is the move its notes planned.
- **Correction to the earlier replay.** Its "12% repeat" came from one sample per decision. With 3 samples the
  default rate on those 40 is 27%, about the base rate, so they weren't unusually random.
- **Costs seen so far.** Unparseable replies rose slightly at low temperature (2–4 in 60, against 1); I didn't
  inspect them. Single replayed decisions can't show whether near-greedy play makes back-and-forth loops
  worse. That needs a full game.

**Full game at temperature 0.2 (`211579962f41`, rolling log, same seed) against default temperature (`bed2ae3c16c5`).**

| Game | Moves into walls | Longest run of the same blocked move | Team distinct cells | Coverage | Reversals (A→B→A) | Exits |
| --- | --- | --- | --- | --- | --- | --- |
| Default temperature | 23.0% | 6 or fewer | 35 | 0.24 | 51 | none |
| **0.2** | **56.3%** | **C 71, B 35, A 6** | **24** | **0.17** | 36 | A at t74 |

- **Low temperature locks agents into loops.** C reached a statue cell at t9, then sent `move: W` into the west
  wall for all 71 remaining turns. Every note read "N=open, E=open, S=wall, W=wall… Path continue…", correct
  about the wall and still the wrong move. B did the same for 35 turns.
- **A self-reinforcing loop.** The prompt hardly changes between turns: the same cell, a near-identical new
  line in the notebook, the same peer ranges. So the same reply comes back. Each repeat adds another
  identical line, which makes the next repeat even more likely. Notes also kept saying "Arrived W from E" after
  blocked moves, copying the template rather than `last_action`.
- **The replay missed this.** Single decisions replayed from real game states improved threefold, but a game
  feeds each output back into the next prompt. Default temperature's randomness was what broke these
  repeats. Reversals fell (51 → 36) only because two agents stopped moving at all.
- **Takeaway:** temperature isn't a free fix for a small model with reasoning off. Options:
  - an engine-side nudge, such as "your last N moves were blocked" in the observation;
  - a moderate temperature;
  - a structure that makes the model look at `last_action` before `move`.

## Haiku on the rolling log (`5d7b5b34b201`, `configs/haiku_v4_landmarks_append_log.json`)
Did the notebook changes made for Qwen help Haiku? Same maze (seed 202611017, 12×12, v4 + 10 landmarks, meeting
notebooks on, 2,048-token cap). The only change is `notebook_ops: append_log`. It's compared with the 5
earlier Haiku runs with the same settings and splices (`landmarks_v4` v4_landmarks ×3, `haiku_pattern` v4 ×2).

| Haiku | Exits | Coverage | Moves into walls | Rejected notebook edits | Reversals (A→B→A) | Distinct cells (team) | Notebook writes | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Splice, 5 runs | A in all (t5–t18); B in 3 of 5 (t32, t32, t64) | 0.36–0.76 | 0–1 | 0 | 4–14 | 66–125 | 6–71 per agent | $0.07–0.09 |
| **Rolling log** | A t5 only | 0.35 | 2 | 0 | **26** | 58 | **78–80 per agent** | **$0.14** |

- **Haiku had no notebook problem to fix.** Across the 5 splice runs, no edit was rejected and none was ever
  deleted. It only ever inserted, and peaked at 0.5–6.8 KB, under the cap.
- **No sign it helped.** This is one game, so it can't show harm, but every measure is at or below the worst splice run:
  - **exits:** B never got out (it did in 3 of 5 before);
  - **coverage:** at the bottom of the earlier range;
  - **reversals:** twice the highest earlier count.
- **It writes every turn.** With splices Haiku skipped many turns. Offered a plain append field, it filled it
  every turn, including A's 75 turns standing on the exit. B's and C's logs hit the cap at t49–51 and started
  dropping their earliest lines, the ones about junctions and spawn.
- **It's twice as expensive.** The notebook block now changes every turn, so the prompt-cache breakpoint after
  the notebooks is rewritten each time. Cache writes went from 176–203k to 612k tokens, and cache reads
  halved. Total input also rose (1.03M against 0.74–0.87M tokens), because notebooks sit near the cap.
- **Takeaway:**
  - **Model-specific:** the rolling log fixes a small model's offset errors, but costs a capable model its
    editorial choice of what to keep.
  - **For a fair comparison:** run it as a per-model setting, not a new default.
  - **On Anthropic:** drop the second cache breakpoint when notebooks change every turn.

## Coordinates, a trail and a quieter log (`coordinates_enabled`, one game each)
- **What the variant adds:** with `rules.coordinates_enabled`, each observation carries
  `coordinates: {position, trail}`. The position is the agent's exact [x, y] counted from its own start (x
  east, y north). The trail holds its positions over the last 30 turns.
- **Two new rules sentences:** they explain these fields and say that the agents' frames differ by a fixed
  offset, which a shared landmark or meeting cell reveals.
- **One rolling-log change:** its rule now says to write only when you learn something new.
- **Setup:** same maze as before (seed 202611017, v4 + 10 landmarks, rolling log).
- **Comparisons:** Haiku against `5d7b5b34b201`, Qwen through Vessel against `bed2ae3c16c5`.

| Game | Exits | Coverage | Distinct cells (team) | Back-and-forth moves | Wall moves | Notes written | Notes with coordinates | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku, rolling log | A t5 | 0.35 | 58 | 26 | 2 | 238 | 0 | $0.14 |
| **Haiku + coordinates** (`1fd674ac2892`) | A t5 | 0.41 | **92** | 19 | 2 | **170** | **169** | $0.11 |
| Qwen, rolling log | none | 0.24 | 35 | 51 | 23.0% | 206 | 0 | $0 |
| **Qwen + coordinates** (`bb8677c622e6`) | A t69 | 0.26 | 37 | 49 | **36.8%** | 163 | 163 | $0 |

**Haiku turned the coordinates into exact exit positions, and the frames into a negotiation.**
- **Coordinates everywhere:** every radio message and nearly every note carried coordinates in the agent's
  own frame ("A-frame [-2,1]").
- **Calibration became the main radio topic:** 33 of 33 messages discussed frames, for example C at t7 asking
  for "the exit cell in my frame, using a landmark or a shared cell".
- **Exact exit estimates:** B and C each estimated the exit from distance readings at several known
  positions. Both were exactly right: B (-6,-2), C (-6,-6).
- **Calibration without meeting:** at t73 B used the exit as the shared cell, combining A's exit at A-frame
  [-2,1] with its own estimate. "B = A + (-4,-3)" is exactly the true offset. C's guess of A's offset,
  (-4,-7), was also right, but C never trusted it.
- **No landmark meeting happened:** B found the piano at t26 and reported it in its own frame at t80. No one
  else saw it, and A sat on the exit throughout.
- **The bottleneck moved from "where" to "how":** B knew the exit's exact cell from t31 and spent the rest of
  the game hunting for a route ("the x=-6 column has no southern route"). B and C were still finding new cells
  at t80. Exploration improved, but not enough for 80 turns.
- **The quieter-notes rule half worked:** 170 notes against 238, and A stopped writing once settled on the
  exit.

**Qwen saw its loops in the trail and kept looping.**
- **Loop awareness:** 59 notes talked about loops. For example, C at t32: "Trail shows repeated loop at
  [2,-2]".
- **No change in behaviour:** at t37 it was "Moving South to [2,-3] to escape loop", into the dead end it had
  marked at t34. At t39: "Must break out of this loop".
- **No improvement:** back-and-forth moves (49 against 51) and distinct cells (37 against 35) barely changed.
  Wall moves rose to 37% (23% before); with one game each that may be noise. A exited at t69.
- **Timeouts:** longer prompts brought the first decision-window timeouts (4).
- **Same pattern as plan inertia:** like the wall-walking, the model reports the state correctly and then
  doesn't act on it.

**Takeaways:**
- **Coordinates are the biggest single lift for Haiku's spatial reasoning so far.** v5 asked it to track its
  own position and only 28% of positions were right. Given exact positions, it did Sonnet-level exit estimation
  and cross-frame arithmetic.
- **They don't fix navigation.** Knowing where the exit is doesn't find a corridor to it. Natural next
  steps:
  - a longer horizon, since B and C were still finding new cells at t80;
  - a way to remember which cells' walls are known, so a route can be planned.
- **For Qwen, more information isn't the lever.** It already narrates its loops correctly.

## Junction bookkeeping: where route-finding breaks
- **The question:** v4 tells agents to note each junction's tried exits and prefer an untried one. Are they
  doing it, and do stale or conflicting notes undermine it?
- **The measure (ground truth, all runs):** at each decision on a junction the agent has stood on before,
  with at least one open exit it has neither left nor arrived through, did it move through an exit it had
  already used?

| Model | Runs | Moves at such revisits | Took an already-used exit |
| --- | --- | --- | --- |
| Sonnet 5.5 | 7 | 29 | **3%** |
| DeepSeek v4.1 Flash | 9 | 63 | 27% |
| Haiku 5.5 | 87 | 568 | **40%** |
| Qwen3.5-9B | 14 | 119 | 58% |
| Haiku + coordinates | 1 | 8 | 0% |

Many of these decisions were STAYs (camping), which are left out of the percentages.

**Reading 8 random Haiku cases (v4) gave the same picture each time.** Haiku labelled an exit it had already
used as untried. For example:
- **77f80e3a3946 t34:** "at junction (N,E,W open, S wall)… Untried: E and W. Trying E." At t25 it had
  logged entering this same cell from the east ("moved W from E-side corridor into cell (N,E,W open, S
  wall), dist 6.0").
- **e56b8582aa5c t49:** "Here N wall, E open, S open, W open. Dist 5.0. Trying W (untried)". At t25 it had
  logged arriving in this exact cell from the west.
- **14f70a14e29d t45:** "at N-brick cell; E,S,W open. Dist 6.4… Trying S (untried)". At t28 it had logged
  coming up from the south into it.

**Two gaps, and stale lines are only part of it:**
- **Every revisit becomes a fresh line.** No model ever deleted notebook text (0 bytes deleted in every
  Haiku and Sonnet run), so a junction's history is spread across journal lines from different ticks.
- **The failure is earlier than reconciling those lines:** the agent doesn't recognise the cell. It
  describes it from scratch by edges and distance, which many cells share, and declares exits untried.
- **Arrival directions aren't counted.** Agents log "Trying N" for exits they leave by, but the exit they
  came in through, equally explored, is never marked tried. Most bad choices re-entered a branch the agent
  had arrived from.
- **Sonnet also only appends,** but it names cells as it goes ("W2 … W is dead", "back at start") and
  recognises them on return. Identity is the difference, not the notebook format.

**Implication:**
- **Coordinates give cells identity,** which is probably why Haiku with coordinates took no used exits
  (8 moves, one game).
- **The remaining gap is planning a route from a scattered journal in one pass without thinking:** B knew
  the exit cell exactly and still couldn't find a way there.
- **Two cheap levers to test:**
  - a rule that the exit you arrived through counts as tried;
  - an engine-kept record of the edges seen at each visited coordinate. That's a "known map", a bigger
    change to what the experiment measures.

## Prompt v7 and a misleading trail rule (Haiku + coordinates, same seed)
- **v7 = v4 plus one sentence:** "The exit you arrived through counts as tried as well: you already know
  where it leads."
- **Run 1 (`3e75a6a13206`):** v7 with the original coordinates wording.
- **Run 2 (`7daa4ff3a048`):** the trail sentence reworded (commit `0521217`).

| Haiku + coordinates | Exits | Coverage | Distinct cells | Back-and-forth | Used-exit choices at junction revisits | Notes doubting position or trail | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v4 (`1fd674ac2892`) | A t5 | 0.41 | 92 | 19 | 0 of 8 | 23 | $0.11 |
| v7 (`3e75a6a13206`) | A t5 | 0.36 | 85 | 22 | 0 of 11 | 22 | $0.11 |
| **v7, trail wording fixed** (`7daa4ff3a048`) | A t5 | **0.45** | **110** | **11** | 0 of 7 | **0** | $0.11 |

**v7 was used but had nothing left to fix.** Notes adopted it ("N open, E open (came from), … Only untried exit is
N"; "Came from S (tried). Trying N (untried)"). With coordinates, Haiku was already taking no used exits at
junction revisits, so there was no gap for it to close.

**The trail wording was a bug of ours.**
- **The ambiguity:** "trail lists where you were on each of the last 30 turns" doesn't say whether the
  current cell is included. It isn't: the trail ends with last turn's cell.
- **How Haiku read it:** it took the last trail entry as its current position, then logged the mismatch
  ("position is [-2,3] (trail lagged)"). C at t12 even went with the trail over the exact position: "state
  position [1,-2] conflicts with trail/notebook [1,-3]; trusting trail for now".
- **The fix:** the reworded rule says the position "is always current and exact" and the trail "ends with
  last turn's cell, so it never includes where you are now". Doubt notes went from 22 per game to 0.
- **Effect:** the best exploration of any Haiku game: 110 distinct cells, back-and-forth halved. B kept a
  frontier list in its own frame ("Untried exits in my frame: [0,0] S, [0,3] S, [-2,3] W") and went back to
  it.

**Why still only one exit: the horizon now binds.**
- **Optimal distances:** with a perfect map, B needs 28 moves to reach the exit and C needs 52 (the oracle
  is 52 ticks).
- **Still exploring:** C was finding new cells at t80, with no stretch over 14 turns without one.
- **The horizon:** these Haiku configs inherited the pilots' 80 turns; the default for 12×12 is 320. Earlier,
  "too short" was wrong because agents stalled by t24. Now they explore steadily, so the horizon is the
  constraint.

**The same setup on Qwen (`015888b15e1b`, through Vessel), against Qwen + coordinates with v4 and the old
wording (`bb8677c622e6`):**

| Qwen + coordinates | Exits | Coverage | Distinct cells | Back-and-forth | Wall moves | Used-exit choices at junction revisits | Notes doubting the trail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v4, old wording | A t69 | 0.26 | 37 | 49 | 36.8% | 6 of 11 | 1 |
| **v7, fixed wording** | none | **0.31** | **45** | **75** | **27.5%** | 4 of 8 | 0 |

- **The wording fix didn't touch Qwen's problem.** Qwen had never doubted the trail (1 note in the earlier
  game), so there was nothing for the fix to remove.
- **The best Qwen exploration so far:** 45 distinct cells, against 35–37 in the other rolling-log games.
  Wall moves were the lowest of the coordinates games.
- **Loops got worse:** A, five cells from the exit, ping-ponged for up to 10 turns (41 reversals) and never
  got there.
- **v7 changed nothing at junction revisits:** Qwen still took an already-used exit about half the time,
  which is its long-run rate (58%).
- **Single games swing this much,** so read this as no clear change. Qwen's bottleneck is still acting on
  what it writes, not what it's told.

## No distance sensors (`distance_sensors: none`, Haiku, `a5e568c02c88`)
- **What changes:** `exit_distance_tenths` and `peer_ranges` are left out of the observation. The
  straight-line distance rule becomes "You have no distance sensors: nothing tells you how far away the
  exit or the other agents are."
- **Setup:** otherwise the same as `7daa4ff3a048` (v7, coordinates with the fixed trail wording, rolling
  log, 10 landmarks, seed 202611017).
- **The question being tested:** were the readings making agents bounce back and forth?
- **The evidence beforehand:** across 8 earlier Haiku games on this seed, 62 of 104 reversals (A→B→A) came
  straight after a move that raised the exit reading.

| Haiku, v7 + coordinates | Exits | Coverage | Distinct cells | Back-and-forth | Notes / radio naming a landmark | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| With distances (`7daa4ff3a048`) | A t5 | 0.45 | 110 | 11 | 6 / 1 | $0.11 |
| **No distances** (`a5e568c02c88`) | A t5 | **0.53** | 115 | 14 | **16 / 8** | $0.11 |

- **Exploration improved a little:** 0.53 coverage is the best Haiku game so far. Back-and-forth didn't
  fall (14 against 11), so the readings weren't the main cause of bouncing in this setup. With coordinates
  and a trail, reversals were already low.
- **Landmarks took over as reference points:** without distances they're the only thing two agents can both
  recognise. Notes and radio named them several times more often.
- **The cost:** without distances, B and C can't work out where the exit is. A radioed the route home
  in its own frame ("[-2,1] in my frame… N,N,W,S,W"). Others noted "offset still unknown, need a shared
  landmark or cell", and no shared cell turned up in 80 turns.
- **Taken with the coordinates games:** distances help locate the exit and convert between frames. They
  hurt less than expected once agents have coordinates.

**Frames on the radio: Haiku labels them, Qwen doesn't.**

| Model | Radio messages with coordinates | Naming whose frame |
| --- | --- | --- |
| Haiku (4 games) | 110 | **109** ("A-frame [-2,1]", "in my frame", "offset unknown") |
| Qwen (2 games) | 30 | **0** ("B moved E to [1,1]") |

Haiku understood the frames from the rule. Qwen sends bare coordinates, so its teammates can't tell they're
in someone else's frame.

## Landmark calibration, and prompt v8: go back and help (no distances)
**Without v8, the data for calibration was there but nobody used it (`a5e568c02c88`).**
- **Shared landmarks:** B and C both stood on four of the same landmarks (ladder, piano, fountain, statue).
- **Both radioed them in their own frames:** fountain at B [-6,1] and C [-6,-3]; statue at B [2,0] and
  C [2,-4]. That gives C = B + (0,-4), confirmed twice, available from t53.
- **C noticed but stopped there.** At t47 it wrote "B reports fountain at its [-6,1], so frames may
  differ by an offset".
- **Neither did the subtraction.** For the rest of the game both asked each other to "send your landmark
  coords to align frames", data they already had.
- **A couldn't help.** It camped on the exit as a "beacon", visited no landmarks, and so its exit
  position could never be converted into anyone else's frame.

**Prompt v8 (`d974c5320ad8`) = v7 plus:** "Once you have reached the exit, standing on it helps nobody:
the others cannot see you there, and the goal only needs each agent to visit it once. Instead, head back
along your known route to find a teammate. When you meet on a cell or both stand on the same landmark,
compare positions to work out the offset between your frames, then give them the route to the exit in their
own frame."

| Haiku, coordinates, no distances | Exits | Coverage | Distinct cells | STAYs | Meetings | Explicit offsets worked out |
| --- | --- | --- | --- | --- | --- | --- |
| v7 (`a5e568c02c88`) | A t5 | 0.53 | 115 | 75 | 0 | 0 |
| **v8** (`d974c5320ad8`) | A t5 | **0.62** | **129** | 42 | B–C once | **1** (B, t51) |

- **A did leave the exit,** reaching cells up to 16 moves away by t25.
- **Then A swapped one fixed post for another.** From t43 it waited at its own start, "A at start [0,0],
  waiting for C", for 37 turns, and radioed the same route 13 times. Nobody else knows where A's start is.
- **A never went to a landmark,** the one move that would have let others convert A's coordinates.
- **B did the calibration v7 runs never did.** At t51: "Offset from C's statue: B = C + (0,4), so C ladder
  [-1,-1] is B [-1,3], C piano [-3,-3] is B [-3,1]…". It's correct, and it was radioed at t64.
- **Exploration was the best of any Haiku game** (0.62), but B and C still ended 44 and 36 moves from the
  exit.
- **What's missing:** the helper needs a shared reference, not just a route. A useful next nudge would be
  "radio the exit's position relative to a landmark", which doesn't depend on any frame.

**Qwen without distances (`f5313c5666ee`, v7 + coordinates), against the same with distances
(`015888b15e1b`):**
- **Wall moves rose:** 33.6% against 27.5%.
- **Exploration fell:** 35 distinct cells against 45, coverage 0.24 against 0.31.
- **Ping-pong fell:** A's runs were 1 turn at most, against 10.
- **No exits:** A ended 2 moves from the exit.
- **Conclusion:** removing distances doesn't help Qwen. Its problems are wall moves and acting against its
  own notes, not chasing a reading.

**Prompt v9 (`fc710288bac3`) = v8 plus:** "When you share where something is (the exit, a dead end, an
untried branch), give it relative to a landmark, for example 'exit is 3 east and 2 south of the piano':
anyone who has found that landmark can use it at once, without knowing your frame. If you know where the
exit is, visiting a landmark so you can describe the exit from it is one of the most useful things you can
do." Every frame has the same axes, so a landmark-relative position needs no calibration.

| Haiku, no distances | Exits | Coverage | Distinct cells | A's STAYs | Landmark-relative exit given |
| --- | --- | --- | --- | --- | --- |
| v8 (`d974c5320ad8`) | A t5 | 0.62 | 129 | ~37 waiting at its start | no |
| **v9** (`fc710288bac3`) | A t5 | 0.44 | 110 | **69 waiting at its start** | no (only relative to "A's start") |

- **The searchers asked the right question.** C at t44: "A: please give your start [0,0] relative to the
  piano, or send your exit position relative to the piano." B at t57 asked the same of the statue. Both
  had visited all four of the landmarks the other one knew.
- **A treated its start as a landmark.** At t6: "It is 2 west and 1 north of A's start [0,0]". Then it
  went back to the start ("Waiting at start as rendezvous for B and C") and stayed there to the end, even
  writing "staying as rendezvous" at t30. At t13 it radioed "2 west and 1 south", contradicting itself.
- **The landmark was close but never visited.** The globe sits next to the exit, and the exit is 1 west
  and 1 north of it, but A never stepped onto it. Haiku follows the letter of "go back and help" (returning
  to a meeting point it chose) but not its point: a reference only it can find.
- **Single game:** v9's lower coverage is mostly B's 10-turn ping-pong, likely noise. What's consistent
  across v8 and v9 is the exit-finder anchoring on its own start.
- **Next nudge, if any:** say outright that your start is not a landmark, because only you can find it.










## Qwen3.5-9B: append/rewrite instead of splices (single games via Vessel)
Splices need exact code-point offsets and the current revision. Qwen got these wrong often, and the rejected
edits left its notes out of order. `rules.notebook_ops = "append_rewrite"` swaps `notebook_edit` for two
fields, `notebook_append` and `notebook_rewrite`, and the engine places the text. Budgets and the cap are
unchanged. All three games use the same maze seed and config (`configs/qwen35_9b_vessel*.json`, not
committed), Qwen3.5-9B with reasoning off, v4 + landmarks, 80 ticks:

| Game | Notebook ops | Notebook rejections | Notebook wipes (shrunk to under half on a rewrite) | Moves into walls | Exits |
| --- | --- | --- | --- | --- | --- |
| `dbef9cc1d9b9` | splice | 37: 17 stale revision, 13 bad span, 4 over budget, 3 action rejected | 6, from bad spans (one went to `","`, one to empty) | 25.4% | A t23 |
| `573778fa8e7c` | append/rewrite | 32: **15 both fields set**, 13 over the cap, 3 over budget, 1 action rejected | **7 deliberate**: 5 rewrites to the string `"null"`, 2 to an echo of the notebook's JSON wrapper | 28.9% | A t9 |
| `1566f8373ef8` | append/rewrite, hardened | 110: **84 over the cap**, **20 both fields set**, 4 over budget, 2 action rejected | **0** (one deliberate compaction, A t55, 8,039 → 1,017 bytes) | 20.1% | A t56 |
| `bed2ae3c16c5` | **rolling log** (`append_log`) | **12**: 9 over budget, 3 action rejected | **0** (the log dropped 6–15k characters of old lines per agent, from t30, t54 and t47) | 23.0% | none |

A's shortest path from spawn is 5 cells, so its exit tick here is noise.

**Hardening fixed the wipes.** In the first append game, Qwen copied the JSON wrapper around its notebook
(`{"owner":"A","revision":34,"text":...}`) into a rewrite, and five times sent `"null"` as the rewrite text,
erasing up to 5,318 bytes. Two changes stopped it: notebooks are now shown as plain text between
`<<<NOTEBOOK X` markers, and blank or `"null"` text counts as no change. No wipes since.

**"Append or rewrite, never both" didn't land.** In the hardened game Qwen still filled both fields 20 times,
usually with near-duplicates of the same note. The rule throws both away, so **21 of 22 rewrite attempts were
cancelled**; the one that went through was A's compaction at t55. It looks schema-driven: every field is
required (nullable), and with reasoning off the model fills each key it is given.

**New failure: notebooks fill up and stay full.** No splice deletions means notebooks only grow. A, B and C
hit the 8,192-byte cap at t38, t49 and t34. From then on every append was rejected (84 in total). The few
compaction attempts all came with an append, so they were cancelled too. B and C finished the game unable to
record anything new.

**Implications:**
- **Make conflicts impossible by construction.** Use one nullable `notebook` field holding `{mode: append|rewrite, text}`, not two fields.
- **Handle a full notebook.** Options: the engine drops the oldest text on overflow (a rolling log), or the
  observation warns near the cap ("rewrite to compact"). Either breaks spec §5.4's "nothing is truncated for
  you", which this variant already departs from.
- **Keep appends at the end.** Newest notes then sit right before the observation, and the notebook's
  prefix stays stable for prompt caching. Prepending would rewrite the start of the notebook block every turn.

**Follow-up: append/rewrite replaced by a rolling log (`notebook_ops = "append_log"`, schema `1.2`).**
- **One field:** each response carries a single `notebook_append`. Rewrite and compaction are gone.
- **The engine maintains the log:** it adds each note on a new line and drops the oldest lines once the
  notebook would pass the cap. `notebook.updated` events record how much was dropped
  (`dropped_codepoints`).
- **Old games need the old code:** the two append/rewrite games above recorded schema `1.1`, which the
  current code no longer reads; replay them at commit `a4b2bcb`.

**Rolling-log result (`bed2ae3c16c5`, same seed, viewed in Vessel as session `bed2ae3c16c5`, tagged A/B/C).**
- **Notebook writes work.** 206 of 240 decisions added a note, against 166 accepted splices. The 12 rejections
  were 9 notes over 1,024 bytes and 3 whole actions rejected. No conflicts, no wipes, no offset errors.
- **Notebooks now hold the last ~25–30 turns.** Each agent wrote ~290 bytes a turn. Once the 8 KB log was full,
  older lines rolled off: A dropped 15,454 characters, B 6,496, C 6,089.
- **Navigation didn't change.** 23% of moves hit walls (splice 25%, append/rewrite 20–29%), coverage 0.24
  (0.20–0.33), revisits 0.78–0.86. No agent reached the exit; A, five cells from it, had done so in the other
  three games, so one game per variant can't tell these apart.
- **Prompt size grows.** A full log means every prompt carries ~8 KB of notes: 700k input tokens over the
  game against 338k for splice, which stayed smaller because Qwen's broken splices kept notebooks short.

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
