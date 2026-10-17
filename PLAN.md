# Build plan

Running plan for implementing [spec.md](spec.md). Ticked as each item lands on `main`.

Decisions recorded:
- Scope for this pass: phases 1–5. Phase 6 (LangChain, ablations) and 7 (Postgres, remote auth) later.
- Pilot model (phase 3): Anthropic `claude-haiku-5-5`, key from `.env` (`ANTHROPIC_API_KEY`).
- Python 3.14 via uv; ruff + pytest are the only dev tools.
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
- [ ] Coordinator: autonomous clock, fixed-deadline / barrier / manual modes, concurrent dispatch, forced no-ops
- [ ] Baselines: uniform open-move, wall follower, bounded DFS (state only in notebook)
- [ ] Persistence: SQLite WAL journal, atomic tick commits, snapshots, invocation ledger, manifest
- [ ] Metrics (§15.2)
- [ ] Replay: playback + deterministic re-execution with hash verification; ZIP export
- [ ] CLI: run headless, replay/verify

## Phase 3 — LLM adapters
- [ ] Provider config (Anthropic / OpenAI-compatible incl. Ollama), per-agent model
- [ ] PydanticAI adapter: one request, no history, no retries
- [ ] Prompt (versioned system instruction + ordered observation), invocation logging
- [ ] Context-capacity preflight
- [ ] Pilot run with `claude-haiku-5-5`

## Phase 4 — Spectator service
- [ ] FastAPI REST reads + commands (idempotency)
- [ ] SSE + WebSocket parity, reconnect from sequence
- [ ] Export endpoint, health
- [ ] Generated OpenAPI / JSON Schema / TS types

## Phase 5 — React viewer
- [ ] Maze SVG, agent inspectors, notebooks, radio archive
- [ ] Timeline / replay scrubber, live follow, metrics panel
