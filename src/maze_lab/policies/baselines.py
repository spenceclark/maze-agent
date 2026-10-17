"""Algorithmic baseline policies (spec §14).

Each policy is immutable. All memory is rebuilt every tick from the agent's own
notebook plus the last-action receipt, under the same budgets an LLM gets.
"""

from dataclasses import dataclass

from maze_lab.agent_contracts import (
    AgentRules,
    Direction,
    LocalCell,
    Move,
    Notebook,
    NotebookEdit,
    Observation,
    TurnAction,
    utf8_len,
)
from maze_lab.config import BaselinePolicyName
from maze_lab.domain.rng import KeyedSampler
from maze_lab.policies.base import AgentPolicy, DecisionAttempt

COMPASS: tuple[Direction, ...] = ("N", "E", "S", "W")  # also clockwise order
# Offsets in the agent's own frame (origin = spawn, east = +x, south = +y).
OWN_STEP: dict[str, tuple[int, int]] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}

type Cell = tuple[int, int]


def _open_dirs(local: LocalCell) -> list[Direction]:
    edges = {"N": local.north, "E": local.east, "S": local.south, "W": local.west}
    return [d for d in COMPASS if edges[d] == "open"]


def _moved_direction(observation: Observation) -> Direction | None:
    """The direction of last tick's successful move, if there was one."""
    movement = observation.last_action.movement
    if movement.outcome == "moved" and movement.attempted not in (None, "STAY"):
        return movement.attempted
    return None


def _can_write(observation: Observation, text: str, replaced: str) -> bool:
    """Whether a splice inserting `text` over `replaced` fits every notebook budget."""
    budgets, nb = observation.budgets, observation.notebook
    size = nb.utf8_bytes - utf8_len(replaced) + utf8_len(text)
    return (
        budgets.notebook_enabled
        and utf8_len(text) <= budgets.notebook_insert_bytes
        and (size <= budgets.notebook_cap_bytes)
    )


def _splice(nb: Notebook, start: int, text: str) -> NotebookEdit:
    """Replace everything from `start` to the end of the notebook with `text`."""
    return NotebookEdit(expected_revision=nb.revision, start=start, end=nb.codepoints, text=text)


def _decision(observation: Observation, move: Move, edit: NotebookEdit | None = None) -> DecisionAttempt:
    action = TurnAction(
        schema_version="1.0", tick=observation.decision_tick, move=move, notebook_edit=edit, radio=None
    )
    return DecisionAttempt(action=action, failure=None)


def _random_open(observation: Observation, sampler: KeyedSampler) -> Move:
    options = _open_dirs(observation.local)
    if not options:
        return "STAY"
    return options[sampler.below(len(options), observation.decision_tick)]


@dataclass(frozen=True)
class RandomOpenPolicy:
    """Uniform choice among open compass edges; no memory."""

    sampler: KeyedSampler

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        return _decision(observation, _random_open(observation, self.sampler))


@dataclass(frozen=True)
class WallFollowerPolicy:
    """Right-hand rule. The notebook holds exactly one letter: the current heading."""

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        if observation.local.is_exit:
            return _decision(observation, "STAY")
        nb = observation.notebook
        stored = next((d for d in COMPASS if d == nb.text), "N")
        heading = _moved_direction(observation) or stored
        i = COMPASS.index(heading)
        preference = [COMPASS[(i + turn) % 4] for turn in (1, 0, 3, 2)]  # right, straight, left, back
        open_dirs = _open_dirs(observation.local)
        move: Direction | None = next((d for d in preference if d in open_dirs), None)
        if move is None:
            return _decision(observation, "STAY")
        edit = _splice(nb, 0, move) if move != nb.text and _can_write(observation, move, nb.text) else None
        return _decision(observation, move, edit)


def _replay(log: str) -> tuple[Cell, set[Cell], list[Cell]]:
    """Rebuild (position, visited, DFS stack) from a log of successful moves."""
    here: Cell = (0, 0)
    visited: set[Cell] = {here}
    stack: list[Cell] = [here]
    for letter in log:
        dx, dy = OWN_STEP[letter]
        here = (here[0] + dx, here[1] + dy)
        if len(stack) >= 2 and here == stack[-2]:
            stack.pop()
        else:
            stack.append(here)
        visited.add(here)
    return here, visited, stack


def _dfs_move(log: str, open_dirs: list[Direction]) -> Move:
    here, visited, stack = _replay(log)

    def neighbour(d: Direction) -> Cell:
        dx, dy = OWN_STEP[d]
        return (here[0] + dx, here[1] + dy)

    fresh: Direction | None = next((d for d in open_dirs if neighbour(d) not in visited), None)
    if fresh is not None:
        return fresh
    if len(stack) >= 2:
        return next(d for d in COMPASS if neighbour(d) == stack[-2])
    return "STAY"


@dataclass(frozen=True)
class BoundedDfsPolicy:
    """Trémaux/DFS in the agent's own coordinates, replayed from an append-only move log.

    The notebook is one letter per successful move. Moves are logged one tick
    late, from the receipt, because a decision cannot see its own outcome.
    """

    sampler: KeyedSampler

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        if observation.local.is_exit:
            return _decision(observation, "STAY")
        nb = observation.notebook
        # ponytail: the log grows <=1 byte/tick, so a 15x15 perfect maze needs <=450 bytes of the
        # 8192 cap. Once the next letter might not fit, the log goes stale for good and the agent
        # falls back to random-open moves. Compact runs (e.g. "NNNN" -> "4N") if caps shrink.
        if not _can_write(observation, "N", ""):
            return _decision(observation, _random_open(observation, self.sampler))
        pending = _moved_direction(observation) or ""
        move = _dfs_move(nb.text + pending, _open_dirs(observation.local))
        edit = _splice(nb, nb.codepoints, pending) if pending else None
        return _decision(observation, move, edit)


def make_baseline(name: BaselinePolicyName, sampler: KeyedSampler) -> AgentPolicy:
    match name:
        case "random_open_v1":
            return RandomOpenPolicy(sampler)
        case "wall_follower_v1":
            return WallFollowerPolicy()
        case "dfs_bounded_v1":
            return BoundedDfsPolicy(sampler)
