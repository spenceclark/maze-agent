# maze-agent

Three LLM (or baseline) agents explore a seeded maze under strict memory and
communication budgets. See [spec.md](spec.md) for the full specification and
[PLAN.md](PLAN.md) for build progress.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run pyright src tests
```

## Running headless

```bash
uv run maze-lab run --policy dfs_bounded_v1 --seed 1   # baseline run, barrier timing
uv run maze-lab verify <run_id>                         # re-execute and check every state hash
uv run maze-lab export <run_id> run.zip                 # replay ZIP with checksums
```

## Spectator API

```bash
uv run maze-lab serve            # http://127.0.0.1:8000/docs
uv run maze-lab schema           # regenerate schemas/openapi.json and agent-contract JSON Schemas
```

LLM agents read provider keys from `.env` by variable name (e.g. `ANTHROPIC_API_KEY`); see
`configs/pilot_haiku.json` for an LLM run config.

## Viewer

```bash
cd ui && npm install && npm run build   # then `uv run maze-lab serve` serves it at /
cd ui && npm run dev                     # dev server on :5173, proxies the API on :8000
```

## Layout

- `src/maze_lab/agent_contracts.py` – everything an agent sees or emits
- `src/maze_lab/config.py` – run configuration
- `src/maze_lab/domain/` – pure simulation: geometry, generation, state, reducer
- `src/maze_lab/observation.py` – the only ground-truth → agent projection
- `src/maze_lab/coordinator.py` – autonomous tick clock, dispatch, atomic commit
- `src/maze_lab/policies/` – policy protocol and baselines
- `src/maze_lab/persistence/` – SQLite journal, snapshots, invocation ledger
- `src/maze_lab/metrics/` – ground-truth scoring
- `src/maze_lab/replay.py`, `runs.py`, `cli.py` – replay/export, run creation, CLI
- `src/maze_lab/service.py`, `src/maze_lab/api/` – run ownership, commands, REST + SSE/WebSocket
- `ui/` – React + TypeScript spectator viewer
