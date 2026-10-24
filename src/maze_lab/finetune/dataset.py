"""Fine-tuning examples from expert games played through the real engine; no LLM calls.

Each decision becomes one chat example: the exact messages the live adapter sends (system instruction
plus one user message per observation block, the way Ollama splits the adapter's content parts) and
the expert's reply as the assistant turn. Prompt settings come from a real `RunConfig`, so the
examples match what a run of that config would send.
"""

import json
import re
import statistics
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import groupby
from math import ceil
from pathlib import Path
from typing import Any

from maze_lab.agent_contracts import (
    AGENT_IDS,
    AgentId,
    AgentRules,
    AppendTurnAction,
    Observation,
    parse_turn_action,
)
from maze_lab.config import LlmAgentConfig, MazeSettings, RunConfig
from maze_lab.domain.events import NotebookUpdated
from maze_lab.domain.generator import generate_maze
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.state import initial_state
from maze_lab.finetune.expert import decide as expert_decide
from maze_lab.finetune.expert import reply_json
from maze_lab.observation import observe, public_rules
from maze_lab.policies.prompt import system_instruction, user_blocks

# Qwen3.5 tokeniser estimate, measured with qwen3.5:9b through Ollama on the helping-hands runs
# (pilot.db 3d8aba6db5d6, 6bfc0e35c876): prompts 3.51-4.10 bytes/token (median 3.7), replies median 3.05.
PROMPT_BYTES_PER_TOKEN = 3.5
REPLY_BYTES_PER_TOKEN = 3.0

_NOTEBOOK_USED = re.compile(r"(\d+) of \d+ bytes used")

type Message = dict[str, str]
type Row = dict[str, Any]  # {"messages": [...], "meta": {...}}
type Decider = Callable[[Observation, list[Message]], str]


class DatasetError(Exception):
    """A game the expert lost, an illegal move, a dropped notebook line, or a replay mismatch."""


def check_target(config: RunConfig) -> LlmAgentConfig:
    """The config must be the setup the expert and prompt assume; returns agent A's LLM config."""
    rules, agent = config.rules, config.agents[0]
    problems = [
        msg
        for ok, msg in (
            (rules.notebook_ops == "append_log", "rules.notebook_ops must be 'append_log'"),
            (
                rules.coordinates_enabled and rules.coordinates_frame == "own_start",
                "rules.coordinates_enabled must be on, in the 'own_start' frame",
            ),
            (rules.used_exits_enabled, "rules.used_exits_enabled must be on"),
            (config.maze.extra_open_edges == 0, "maze.extra_open_edges must be 0 (the expert needs a tree)"),
            (
                isinstance(agent, LlmAgentConfig) and agent.action_field_order == "check_first",
                "agent A must be an LLM agent with action_field_order 'check_first'",
            ),
        )
        if not ok
    ]
    if problems:
        raise DatasetError("; ".join(problems))
    assert isinstance(agent, LlmAgentConfig)
    return agent


def game_config(base: RunConfig, seed: int, size: int) -> RunConfig:
    """`base` on a size x size maze; the horizon covers a full depth-first search (2 moves per cell)."""
    maze = MazeSettings.model_validate({**base.maze.model_dump(), "width": size, "height": size})
    return base.model_copy(update={"root_seed": seed, "maze": maze, "horizon_ticks": 2 * size * size})


def prompt_messages(rules: AgentRules, obs: Observation, prompt_version: str) -> list[Message]:
    system = system_instruction(rules, obs.agent_id, prompt_version, with_check=True)
    blocks = user_blocks(obs, "append_log")
    return [{"role": "system", "content": system}, *({"role": "user", "content": b} for b in blocks)]


def play(config: RunConfig, decide: Decider) -> list[Row]:
    """One full game; `decide` answers every decision of an agent that has not reached the exit yet.

    Agents that have reached the exit stand still and are not recorded: those turns teach no search.
    Raises DatasetError unless every recorded move succeeds and every agent reaches the exit.
    """
    m, rules = config.maze, config.rules
    maze = generate_maze(config.root_seed, m.width, m.height, m.extra_open_edges, m.landmark_count)
    agent_rules = public_rules(rules, m.landmark_count > 0)
    state = initial_state(maze)
    rows: list[Row] = []
    where = f"seed {config.root_seed} size {m.width}"
    while state.objective_met_tick is None:
        if state.tick >= config.horizon_ticks:
            raise DatasetError(f"{where}: not every agent reached the exit in {config.horizon_ticks} ticks")
        submissions: dict[AgentId, Submission] = {}
        searching: list[AgentId] = []
        for agent_id in AGENT_IDS:
            obs = observe(maze, rules, state, agent_id)
            if obs.has_reached_exit:
                action = AppendTurnAction(
                    schema_version="1.2",
                    tick=obs.decision_tick,
                    move="STAY",
                    notebook_append=None,
                    radio=None,
                )
            else:
                messages = prompt_messages(agent_rules, obs, config.prompt_version)
                reply = decide(obs, messages)
                action = parse_reply(reply)
                searching.append(agent_id)
                meta = {
                    "seed": config.root_seed,
                    "size": m.width,
                    "agent": agent_id,
                    "tick": obs.decision_tick,
                }
                rows.append({"messages": [*messages, {"role": "assistant", "content": reply}], "meta": meta})
            submissions[agent_id] = Submission(action=action, failure=None)
        state, events = resolve(maze, rules, state, submissions)
        for agent_id in searching:
            movement = state.agent(agent_id).last_receipt.movement
            if movement.outcome != "moved":
                raise DatasetError(
                    f"{where} tick {state.tick}: {agent_id} {movement.attempted} {movement.outcome}"
                )
        for e in events:
            if isinstance(e, NotebookUpdated) and e.dropped_codepoints:
                raise DatasetError(f"{where} tick {state.tick}: {e.agent_id}'s notebook dropped old lines")
    return rows


def parse_reply(reply: str) -> AppendTurnAction:
    action = parse_turn_action(reply, "append_log", with_check=True)
    assert isinstance(action, AppendTurnAction)
    return action


def expert(obs: Observation, messages: list[Message]) -> str:
    return reply_json(obs, expert_decide(obs))


def schedule(seed: int, games: int, sizes: list[int]) -> list[tuple[int, int]]:
    """(seed, size) per game: consecutive seeds, sizes in turn."""
    return [(seed + i, sizes[i % len(sizes)]) for i in range(games)]


@dataclass
class Stats:
    games: int = 0
    won: int = 0
    failures: list[str] = field(default_factory=list)
    decisions: int = 0
    tokens: list[int] = field(default_factory=list)  # estimated prompt + reply tokens per example
    reply_tokens: list[int] = field(default_factory=list)
    notebook_bytes: int = 0  # largest notebook any prompt showed
    by_size: dict[int, int] = field(default_factory=dict)  # decisions per maze size


def _estimate(row: Row) -> tuple[int, int]:
    *prompt, reply = row["messages"]
    prompt_bytes = sum(len(m["content"].encode()) for m in prompt)
    reply_bytes = len(reply["content"].encode())
    return ceil(prompt_bytes / PROMPT_BYTES_PER_TOKEN), ceil(reply_bytes / REPLY_BYTES_PER_TOKEN)


def write_games(base: RunConfig, games: list[tuple[int, int]], out: Path) -> Stats:
    """Play each game with the expert and write its examples as JSONL; lost games are left out."""
    check_target(base)
    stats = Stats()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for seed, size in games:
            stats.games += 1
            try:
                rows = play(game_config(base, seed, size), expert)
            except DatasetError as e:
                stats.failures.append(str(e))
                continue
            stats.won += 1
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                prompt_tokens, reply_tokens = _estimate(row)
                stats.tokens.append(prompt_tokens + reply_tokens)
                stats.reply_tokens.append(reply_tokens)
                used = _NOTEBOOK_USED.search(row["messages"][1]["content"])
                stats.notebook_bytes = max(stats.notebook_bytes, int(used[1]) if used else 0)
            stats.decisions += len(rows)
            stats.by_size[size] = stats.by_size.get(size, 0) + len(rows)
    return stats


def read_rows(path: Path) -> Iterator[Row]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def verify(base: RunConfig, rows: Iterable[Row]) -> int:
    """Replay every game in `rows` through the engine with the recorded replies.

    Checks each recorded prompt against a freshly built one, every move succeeds, the notebook never
    drops a line, and every agent reaches the exit. Returns the number of games; raises DatasetError.
    """
    games = 0
    for (seed, size), group in groupby(rows, key=lambda r: (r["meta"]["seed"], r["meta"]["size"])):
        recorded, game = iter(group), f"seed {seed} size {size}"

        def replay(
            obs: Observation, messages: list[Message], recorded: Iterator[Row] = recorded, game: str = game
        ) -> str:
            row = next(recorded, None)
            here = f"{game} tick {obs.decision_tick} agent {obs.agent_id}"
            if row is None or (row["meta"]["agent"], row["meta"]["tick"]) != (
                obs.agent_id,
                obs.decision_tick,
            ):
                raise DatasetError(f"{here}: no recorded decision")
            if row["messages"][:-1] != messages:
                raise DatasetError(f"{here}: recorded prompt differs from the engine's")
            return row["messages"][-1]["content"]

        play(game_config(base, seed, size), replay)
        if next(recorded, None) is not None:
            raise DatasetError(f"{game}: decisions recorded after the game ended")
        games += 1
    return games


def _quantiles(values: list[int]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    pick = [ordered[min(len(ordered) - 1, int(q * len(ordered)))] for q in (0.5, 0.9, 0.99)]
    return f"min {ordered[0]}, median {pick[0]}, p90 {pick[1]}, p99 {pick[2]}, max {ordered[-1]}"


def report(name: str, stats: Stats, games: list[tuple[int, int]]) -> str:
    seeds = [s for s, _ in games]
    lines = [
        f"## {name}",
        f"- games: {stats.games} (seeds {seeds[0]}-{seeds[-1]})" if seeds else "- games: 0",
        f"- expert success: {stats.won}/{stats.games} games, every agent reached the exit"
        + (f" ({stats.won / stats.games:.0%})" if stats.games else ""),
        f"- decisions (examples): {stats.decisions}; by maze size: "
        + ", ".join(f"{s}x{s} {n}" for s, n in sorted(stats.by_size.items())),
        f"- tokens per example, prompt + reply (Qwen estimate): {_quantiles(stats.tokens)};"
        f" total {sum(stats.tokens):,}",
        f"- reply tokens: {_quantiles(stats.reply_tokens)}",
        f"- largest notebook shown: {stats.notebook_bytes} bytes (cap 8192; no line ever dropped)",
    ]
    if stats.tokens:
        lines.append(f"- mean tokens per example: {statistics.fmean(stats.tokens):.0f}")
    lines += [f"- lost: {msg}" for msg in stats.failures]
    return "\n".join(lines)
