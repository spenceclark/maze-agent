# Build plan

Running plan for implementing [spec.md](spec.md). Ticked as each item lands on `main`.

Decisions recorded:
- Scope for this pass: phases 1–5. Phase 6 (LangChain, ablations) and 7 (Postgres, remote auth) later.
- Pilot model (phase 3): Anthropic `claude-haiku-5-5`, key from `.env` (`ANTHROPIC_API_KEY`).
- Python 3.14 via uv; dev tools are ruff, pyright (pylance parity), pytest.
- Randomness: SHA-256 counter streams (`domain/rng.py`), not `random.Random`, so draws are stable across Python versions.
- Prompt `maze_agent_v2` (post-pilot): observation split into stability-ordered blocks with Anthropic cache
  breakpoints; cache tokens recorded. Preflight uses `context_bytes_per_token` (default 1.5) plus a per-request
  guard that never sends an over-budget prompt. See OBSERVATIONS.md.
- Prompt `maze_agent_v3`: rules add that straight-line distance ignores walls, so a local minimum can be a dead
  end. An omitted `horizon_ticks` now scales with maze area (500 for 15×15, 320 for 12×12, 109 for 7×7), and run
  creation warns when the horizon is below the omniscient minimum for that maze.
- Prompt `maze_agent_v4` (default): rules add a junction-tracking habit. v3 and v4 are both runnable, so
  batches can compare prompt versions as conditions.
- Deferred to phase 6 (config rejects non-default values until then): checkpoints, distance-sensor variants.

## Phase 1 — Contracts and pure engine
- [x] uv project scaffold, ruff config
- [x] `agent_contracts.py`: §7 models, invariants, strict JSON action parsing
- [x] `config.py`: `RunConfig` (§8.1) with validation
- [x] `domain/`: geometry + distance, seeded streams, maze model, `dfs_v1` generator
- [x] `domain/`: notebook splice, radio eligibility, world state, events, simultaneous reducer
- [x] `observation.py`: sole ground-truth → agent projection
- [x] Tests: §17 rule fixtures + generator properties (252 passing; ruff + pyright clean)

## Phase 2 — Headless experiment runner
- [x] Coordinator: autonomous clock, fixed-deadline / barrier / manual modes, concurrent dispatch, forced no-ops
- [x] Baselines: uniform open-move, wall follower, bounded DFS (state only in notebook)
- [x] Persistence: SQLite WAL journal, atomic tick commits, snapshots, invocation ledger, manifest
- [x] Metrics (§15.2)
- [x] Replay: playback + deterministic re-execution with hash verification; ZIP export
- [x] CLI: run headless, replay/verify (`maze-lab run|resume|verify|export|show|list`)

Phase 2 check (15×15, seed 20261017): dfs 326 ticks, wall follower 217, random hits the 500-tick limit; `verify` matches all hashes.

## Phase 3 — LLM adapters
- [x] Provider config (Anthropic / OpenAI-compatible incl. Ollama), per-agent model
- [x] PydanticAI adapter: one request, no history, no retries
- [x] Prompt (versioned system instruction + ordered observation), invocation logging
- [x] Context-capacity preflight
- [x] Pilot run with `claude-haiku-5-5` (`configs/pilot_haiku.json`)

Phase 3 pilot (7×7, seed 20261017, barrier, 80 ticks, `native` output mode): 240/240 decisions valid,
1 request each, no timeouts/refusals/rejected writes; A exited at t12, B at t31, C still exploring at t80
(`tick_limit`). Agents compacted notebooks and radioed routes. Cost $0.12, p50 latency 2.5 s.
`verify` matched all 80 state hashes.

Notes: Haiku 5.5 rejects non-default temperature/top_p (leave `sampling` empty) and thinks adaptively
by default; `reasoning_tokens` is not reported separately by the provider.


## Phase 4 — Spectator service
- [x] FastAPI REST reads + commands (idempotency)
- [x] SSE + WebSocket parity, reconnect from sequence
- [x] Export endpoint, health
- [x] Generated OpenAPI + JSON Schemas (`maze-lab schema` → `schemas/`); TS types generated in phase 5

Server: `uv run maze-lab serve` (single process, loopback by default; set `MAZE_LAB_SPECTATOR_TOKEN` /
`MAZE_LAB_OPERATOR_TOKEN` for remote use). Runs keep going with no client connected and are re-adopted on restart.


## Phase 5 — React viewer
- [x] Maze SVG, agent inspectors, notebooks, radio archive
- [x] Timeline / replay scrubber, live follow, metrics panel

Viewer: `ui/` (Vite + React + TS, types generated from `schemas/openapi.json`). `npm run build` in `ui/`, then
`uv run maze-lab serve` serves it at http://127.0.0.1:8000/. Live updates use SSE; the WebSocket endpoint is
equivalent (needs the `websockets` package, now a dependency). Checked in a browser: pilot replay (tick-13 radio
heard at decision 14, agent view, notebooks/diffs) and a live baseline run (follow, scrub without pausing,
operator pause/step/resume). 11 vitest tests cover live follow, seek, duplicate delivery, and gap → resync.

## Phase 6 — Comparative experiments (in progress)
- [x] Paired batch runner: spec (conditions × seeds × replicates), seeded shuffled order, parallel, resumable,
  spec-hash guard (`maze-lab batch`); bootstrap report by seed with paired differences (`maze-lab report`)
- [ ] LangChain adapter
- [ ] Cooperative / frontier baselines
- [x] Landmarks: `maze.landmark_count`, seeded placement on a separate stream (maze unchanged), unique labels,
  visible on the current cell only, rules sentence when enabled, drawn in the viewer
- [x] Sensor variant: `rules.distance_sensors = "none"` (no exit distance or peer ranges)
- [x] Rules variants for weaker models, all off by default with default prompts byte-identical:
  `notebook_ops = "append_log"` (rolling log), `coordinates_enabled` (position from own start + 30-turn
  trail), `used_exits_enabled` (current cell's already-used directions)
- [x] Output-shape options per LLM agent: `action_field_order` = `note_first` / `check_first` (required,
  unstored scratch line before the move)
- [x] Prompt versions v6–v10 (restate edges; arrival exit counts as tried; go back and help; landmark-relative
  positions; your start is not a landmark)
- [x] Vessel proxy headers on every LLM request (session = run id, tag = agent)
- [x] Baseline on current code, one game each: Haiku, Sonnet 5.5, Opus 5.5; local reference: qwen3.5:9b,
  lfm2.5, command-r7b (see OBSERVATIONS.md rows 21–26)
- [x] Longer horizons: 120-turn Sonnet baseline (team success t110); 10x10 five-model baseline (Sonnet t88)
- [x] Prompt v11, shared-frame control (`coordinates_frame`), meeting alert (`meeting_alert_enabled`);
  OpenRouter reasoning effort; Haiku team successes at t120 (shared frame) and t91 (meeting alert)
- [x] Haiku on 9x9-17x17 mazes, 600 turns: team success on 4 of 5 (`experiments/haiku_sizes_600.json`)
- [ ] Replicates (3+ seeds) of the best Haiku setup before trusting single-game orderings
- [ ] "Keep exploring and split the unexplored area" nudge for games where nobody finds the exit
- [ ] Remaining ablation variants (checkpoints)

## Next (not started)
- Phase 7: PostgreSQL / separate coordinator, retention jobs, remote auth hardening.
