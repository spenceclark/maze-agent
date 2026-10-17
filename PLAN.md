# Build plan

Running plan for implementing [spec.md](spec.md). Ticked as each item lands on `main`.

Decisions recorded:
- Scope for this pass: phases 1–5. Phase 6 (LangChain, ablations) and 7 (Postgres, remote auth) later.
- Pilot model (phase 3): Anthropic `claude-haiku-5-5`, key from `.env` (`ANTHROPIC_API_KEY`).
- Python 3.14 via uv; dev tools are ruff, pyright (pylance parity), pytest.
- Randomness: SHA-256 counter streams (`domain/rng.py`), not `random.Random`, so draws are stable across Python versions.
- Deferred to phase 6 (config rejects non-default values until then): landmarks, checkpoints, distance-sensor variants.

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
- [ ] FastAPI REST reads + commands (idempotency)
- [ ] SSE + WebSocket parity, reconnect from sequence
- [ ] Export endpoint, health
- [ ] Generated OpenAPI / JSON Schema / TS types

## Phase 5 — React viewer
- [ ] Maze SVG, agent inspectors, notebooks, radio archive
- [ ] Timeline / replay scrubber, live follow, metrics panel
