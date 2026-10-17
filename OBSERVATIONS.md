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
| 6 | All of the above | **Swap model:** Sonnet 5.5, same config (single run) | **Team objective met at t70**, the first LLM success. It built landmark-anchored coordinates, estimated the exit's position, took detours, and followed a peer's route from a landmark | Cost ~22×. Batch replication pending |
| 7 | Can Haiku be pushed into Sonnet's habits? | Prompt v5: spell out coordinates, exit estimation and landmark-anchored routes; plus higher thinking effort | *Pending (`experiments/haiku_pattern.json`)* | — |

**What Haiku did well unprompted:**
- **Notebook use from turn one:** concise journals, one line per turn.
- **Logging one tick late:** it recorded moves only once the next observation confirmed them, as the
  bounded-DFS baseline does.
- **Radioing** useful facts, such as the exit cell's walls.
- **Occasional self-correction** ("labels look swapped vs obs, trust obs").
- **Checking a peer's claim with its sensors:** "My exit dist 3.2 equals my range to A, so A on exit is
  consistent".

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
