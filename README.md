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

## Fine-tuning a local model (Qwen3.5-4B)

Qwen3.5-9B reads its cell correctly once scaffolded but cannot search from memory. The plan is supervised
fine-tuning of **Qwen3.5-4B** on expert demonstrations. No LLM calls and no
human labels go into the dataset.

```bash
uv run maze-lab dataset --games 40 --sizes 8,10,12,15 --out data/train.jsonl   # + data/eval.jsonl, data/train.report.md
```

- **Expert** (`src/maze_lab/finetune/expert.py`): depth-first search that sees only the agent's observation and
  its own notebook, never the maze. In a perfect maze an open exit missing from `used_exits` always leads somewhere
  new. So the rule is: take an untried exit (N, E, S, W order). If there is none, go back: at a dead end, out the one
  exit; in a corridor, out the exit you did not arrive by; at a junction, the way written in the notebook. That last
  case is the only thing that needs memory. On first arrival at each junction the expert appends
  `junction [3,-2] back W`, plus `landmark piano at [3,-2]` for landmarks. Each reply's `check` spells out
  the derivation (edges, arrival, used, untried, and the rule or notebook line that decides).
- **Notebook format:** the target keeps `notebook_ops: append_log`. Junction lines never change, so nothing has to
  be rewritten. A 15x15 maze needs under 1 KB of the 8 KB cap (largest seen: 875 bytes), so the rolling log never
  drops a line, and the generator fails if it ever does. A splice or rewrite format would only add offsets for
  the model to get wrong.
- **Prompts** come from the target config (`--config`, default `configs/qwen35_9b_v10_helping_hands_nothink.json`:
  v10, coordinates, no distance sensors, `check_first`, `used_exits`, 10 landmarks). Each example is `system` plus
  three `user` messages, one per observation block, because Ollama splits the adapter's content parts that way.
  `tests/test_finetune.py` checks this against the live adapter's wire request. Each line also has
  `meta` (seed, size, agent, tick).
- **Verification:** every game is replayed from the written file through the engine. The replay checks that each
  prompt is identical, no move hits a wall, no notebook line is dropped, and every agent reaches the exit.
  Held-out games use the seeds right after the training seeds (`--eval-games`, default 8).
- **Not taught:** radio, merging teammates' notebooks, and what to do after reaching the exit (those turns are not
  recorded), and mazes with loops (`extra_open_edges` must be 0).

Default run (40 games, seeds 1-40): 12,612 examples, expert success 40/40. Tokens per example are about 1.9K
(min 1,739, p99 2,020, max 2,080; estimated at 3.5 bytes per token, as measured on qwen3.5:9b in Ollama). By
decision: 66% take an untried exit, 25% walk a corridor back, 6% leave a dead end, and **3% read a junction line
from the notebook**. That 3% is the skill Qwen lacks, so oversample those rows: their reply contains
`notebook says junction`.

### Training Qwen3.5-4B with Unsloth (QLoRA, 8 GB card)

Training runs in its own CUDA environment, separate from the project's Python 3.14 one:

```bash
uv venv --python 3.12 ../unsloth-env
uv pip install --python ../unsloth-env/Scripts/python.exe torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install --python ../unsloth-env/Scripts/python.exe unsloth
../unsloth-env/Scripts/python.exe training/train_qwen.py --out outputs/maze-qwen4b     # ~2.5 h on an RTX 3070
../unsloth-env/Scripts/python.exe training/export_ollama.py outputs/maze-qwen4b/checkpoint-150 --name maze-qwen4b
```

- **`training/train_qwen.py`:** 4-bit QLoRA, r=16, on the full-attention, linear-attention (gated delta net) and
  MLP projections. It uses 3,000 random examples plus two extra copies of every junction-lookup example, one
  epoch, and loss on the reply only. It prints how many tokens of example 0 carry loss, so a broken mask shows up
  at once. Afterwards it generates replies to 40 held-out prompts and reports valid JSON, agreement with the
  expert's move, and agreement on junction lookups.
- **Rendering:** Ollama formats `qwen3.5` with a built-in renderer, not a template. With thinking off it emits
  `<|im_start|>role
...<|im_end|>` for the system message and for each user message (consecutive user messages
  stay separate), then `<|im_start|>assistant
<think>

</think>

`. The script builds exactly that text,
  so no HF chat template is involved.
- **QLoRA caveat:** Unsloth advises against 4-bit training for Qwen3.5 (larger-than-usual quantization error).
  bf16 LoRA on the 4B needs about 10 GB, so on 8 GB it is QLoRA, the 2B in bf16, or a rented GPU. We chose
  QLoRA and judge it by the live eval.
- **First result (OBSERVATIONS row 38):** checkpoint-150 learned the local rules (124 of 125 searching moves
  match the expert; 173 distinct cells against 74 for the 9B) but **not to write junction notes**. The " new"
  in "new junction" costs 3.3–3.8 nats, so it can't backtrack through junctions. Check note writing, not only
  moves (`--adapter ... --notes-only`), before exporting. Trust the eval loss over the logged training loss,
  which read ~3e-5 while held-out was 0.0029.
- **8 GB pitfalls:** in-loop eval is off by default (after one eval, steps slowed 18x as VRAM spilled into
  system memory), and Ollama models must be unloaded (`ollama stop`) before training or checking on the GPU.
- **`training/export_ollama.py`:** merges the LoRA into 16-bit weights, converts and quantizes to Q4_K_M with
  llama.cpp (Unsloth Studio's prebuilt copy in `~/.unsloth/llama.cpp`), and runs `ollama create` with the
  `qwen3.5` renderer and parser and the same sampling parameters as `qwen3.5:4b`.
- **Evaluate live:** copy `configs/qwen35_9b_v10_helping_hands_nothink.json` and set `"model": "maze-qwen4b"`.
  Run it on the held-out seeds (41-48, sizes as listed in `data/train.report.md`) and on the usual seed 202611017.
  Compare with the 9B base on the share of turns spent on fully explored cells.

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
- `src/maze_lab/finetune/` – expert demonstrations for fine-tuning (`maze-lab dataset`)
- `training/` – Unsloth QLoRA training and Ollama export (own CUDA environment)
- `ui/` – React + TypeScript spectator viewer
