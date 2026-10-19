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
uv run maze-lab run --policy dfs_bounded_v1 --seed 1   # baseline run, barrier timing; horizon scales with maze size
uv run maze-lab verify <run_id>                         # re-execute and check every state hash
uv run maze-lab export <run_id> run.zip                 # replay ZIP with checksums
uv run maze-lab transcript <run_id>                     # transcripts/<run_id>/{A,B,C}.jsonl, one line per turn
```

## Experiments

A spec crosses named conditions (config overrides) with seeds and replicates; every condition sees the same
mazes, so comparisons are paired by seed. See `experiments/` for examples.

```bash
uv run maze-lab batch experiments/radio_ablation_v3.json --dry-run     # list the cells, no cost
uv run maze-lab batch experiments/radio_ablation_v3.json --parallel 3  # run or resume
uv run maze-lab report radio_ablation_v3 --baseline radio_on --out report.md
```

Reports give means with 95% bootstrap intervals, resampled by seed (by replicate if there is only one seed),
plus paired differences from the baseline condition. Crashed or cancelled runs are excluded and listed.

## Variants (the "fixes" you can switch on or off)

Everything below is off by default. With all of them off, prompts and state hashes are byte-identical to the
spec baseline. Findings for each are in `OBSERVATIONS.md`; the "Ladder" column gives the summary-table row.

**World and rules** (`rules.*`, `maze.*` in a run config)

| Switch | Values (default first) | What it changes | Ladder |
| --- | --- | --- | --- |
| `maze.landmark_count` | `0` … | Unique labelled cells, seen only while standing on them | 5 |
| `rules.distance_sensors` | `"exit_and_peers"`, `"none"` | `"none"` drops exit distance and peer ranges, and says so in the rules | 16 |
| `rules.coordinates_enabled` | `false`, `true` | Exact `[x, y]` from the agent's own start (x east, y north), plus its last 30 positions | 13, 15 |
| `rules.coordinates_frame` | `"own_start"`, `"team"` | `team`: everyone counts from A's start, so no frame conversion is needed (a control) | 30 |
| `rules.used_exits_enabled` | `false`, `true` | Lists the current cell's directions the agent has already moved through | 25 |
| `rules.meeting_alert_enabled` | `false`, `true` | Names teammates on your cell (`colocated_with`), with a rule to copy what you lack and record their position | 31 |
| `rules.notebook_ops` | `"splice"`, `"append_log"` | `append_log`: one `notebook_append` field. The engine adds it as a new line and drops the oldest lines past the cap. Notebooks are shown as plain text; blank or `"null"` means no note | 10, 12 |
| `rules.radio_enabled`, `rules.meeting_notebooks_enabled`, `rules.allow_stay` | `true`, `false` | Spec ablations: radio, reading colocated notebooks, STAY | 3 |

**Per LLM agent** (`agents[*].*`)

| Switch | Values (default first) | What it changes | Ladder |
| --- | --- | --- | --- |
| `action_field_order` | `"move_first"`, `"note_first"`, `"check_first"` | Requested key order (needs `append_log`). `note_first` asks for the note before the move. `check_first` adds a required, unstored `check` line before both: edges, arrival direction, exits already taken, chosen direction. Only matters for models that write keys in schema order | 22–24 |
| `effort` | unset, `none` … `max` | Reasoning effort. `none` turns thinking off on Ollama/OpenAI-compatible servers | 7b, 9 |
| `sampling.temperature` | unset, number | Unset uses the model's default | 11 |
| `max_output_tokens`, `context_window_tokens`, `context_bytes_per_token` | | Output cap, and the preflight context budget | 7c |

**Prompt version** (`prompt_version`). Each adds sentences to the rules; v8–v11 are cumulative.

| Version | Builds on | Adds | Ladder |
| --- | --- | --- | --- |
| `maze_agent_v3` | — | Straight-line distance ignores walls; a local minimum can be a dead end | 2 |
| `maze_agent_v4` (default) | v3 | Note each junction and the exits tried; prefer an untried one | 4 |
| `maze_agent_v5` | v4 | Keep coordinates, estimate the exit, anchor shared routes on landmarks | 7a |
| `maze_agent_v6` | v4 | Restate your four edges before choosing; don't repeat a blocked direction | 9 |
| `maze_agent_v7` | v4 | The exit you arrived through counts as tried | 15 |
| `maze_agent_v8` | v7 | Once you've reached the exit, go back and help: meet, find your frame offset, give the route | 17 |
| `maze_agent_v9` | v8 | Give positions relative to a landmark; visit one if you know where the exit is | 18 |
| `maze_agent_v10` | v9 | Your own start is not a landmark | 19 |
| `maze_agent_v11` | v10 | Copy what you lack from a teammate's notebook when you meet; don't wait, go to a described landmark | 30, 31 |

Always on (not switchable):
- straight-line distance quantised in tenths;
- the trail wording "ends with last turn's cell" (coordinates only);
- "write a note only when you learn something new" (`append_log` only).

**The current best setups** (one game each, seed 202611017):
- **Hosted:** `configs/{haiku,sonnet55,opus55}_v10_landmarks_coords_nodist.json`: v10, landmarks,
  coordinates, no distances, `append_log`.
- **Local Qwen3.5-9B:** the same plus `action_field_order: "check_first"` and `effort: "none"`.

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
- `src/maze_lab/replay.py`, `export.py`, `transcript.py`, `runs.py`, `cli.py` – replay, export, per-agent transcripts, run creation, CLI
- `src/maze_lab/service.py`, `src/maze_lab/api/` – run ownership, commands, REST + SSE/WebSocket
- `src/maze_lab/batch.py`, `analysis.py` – paired experiment batches and bootstrap reports
- `ui/` – React + TypeScript spectator viewer
