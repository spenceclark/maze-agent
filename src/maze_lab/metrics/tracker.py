"""Incremental run metrics (spec §15.2).

`MetricsTracker` is fed every committed tick in order and derives everything
from the previous state, the new state, and the tick's events. It uses no
clock or randomness, so replaying ticks from S_0 rebuilds an identical
snapshot. Ground truth: never import from observation or policy code.

Conventions:
- Byte counts are UTF-8 bytes. Deleted bytes are the UTF-8 size of the
  removed code-point range of the old text.
- Coverage, co-location ticks, and meeting episodes include S_0.
- Ratios are None when their denominator is zero (path efficiency is None
  for agents that have not exited).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import Literal, get_args

from maze_lab.agent_contracts import (
    AGENT_IDS,
    AgentId,
    Contract,
    ForcedStayCause,
    NotebookRejection,
    RadioRejection,
    utf8_len,
)
from maze_lab.config import RulesConfig
from maze_lab.domain.events import NotebookUpdated
from maze_lab.domain.geometry import Position
from maze_lab.domain.maze import MazeDefinition
from maze_lab.domain.radio import next_eligible_tick
from maze_lab.domain.reducer import TickResult
from maze_lab.domain.state import WorldState
from maze_lab.policies.base import Usage

PAIRS: tuple[tuple[AgentId, AgentId], ...] = tuple(combinations(AGENT_IDS, 2))


class PairMetrics(Contract):
    colocated_ticks: int  # states S_0..S_t in which the pair shares a cell
    episodes: int  # transitions into co-location; co-location at S_0 counts


class AgentMetrics(Contract):
    first_exit_tick: int | None
    # Movement
    successful_moves: int  # individual path length
    blocked: int
    stayed: int  # deliberate STAY
    forced_stays: int
    forced_stays_by_cause: dict[str, int]
    revisits: int
    revisit_fraction: float | None  # revisits / successful_moves
    shortest_path_to_exit: int
    moves_to_first_exit: int | None
    path_efficiency: float | None  # shortest_path_to_exit / moves_to_first_exit
    # Decision reliability: valid + forced_stays == scheduled
    scheduled_decisions: int
    valid_decisions: int
    # Radio
    radio_accepted: int
    radio_bytes: int
    radio_rejected_by_code: dict[str, int]
    radio_eligible_ticks: int | None  # None when rules are unknown
    # Notebook
    notebook_bytes: int
    notebook_peak_bytes: int
    notebook_inserted_bytes: int
    notebook_deleted_bytes: int
    notebook_revisions: int
    notebook_rejected_by_code: dict[str, int]
    notebook_cap_bytes: int | None
    notebook_cap_pressure: float | None  # peak / cap
    # Resource use (None when never reported)
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    provider_requests: int
    estimated_cost_usd: float | None


class RunMetrics(Contract):
    version: Literal["metrics_v1"] = "metrics_v1"
    tick: int
    objective_met_tick: int | None
    first_exit_tick: int | None
    oracle_ticks: int  # max_i shortest_path(spawn_i, exit)
    reachable_cells: int
    covered_cells: int
    coverage: float  # covered_cells / reachable_cells
    shared_cells: int  # visited by at least two agents
    redundant_exploration: float  # shared_cells / covered_cells
    meetings: dict[str, PairMetrics]  # "A-B", "A-C", "B-C"
    agents: dict[AgentId, AgentMetrics]  # A, B, C


def _counter(codes: object) -> dict[str, int]:
    return dict.fromkeys(get_args(codes), 0)


def _ratio(num: int, den: int | None) -> float | None:
    return num / den if den else None


def _add[N: (int, float)](total: N | None, value: N | None) -> N | None:
    return total if value is None else (total or 0) + value


@dataclass
class _AgentTally:
    spawn: Position
    shortest_path_to_exit: int
    visited: set[Position]
    first_exit_tick: int | None = None
    moves: int = 0
    blocked: int = 0
    stayed: int = 0
    forced_by_cause: dict[str, int] = field(default_factory=lambda: _counter(ForcedStayCause))
    revisits: int = 0
    moves_to_first_exit: int | None = None
    radio_accepted: int = 0
    radio_bytes: int = 0
    radio_rejected: dict[str, int] = field(default_factory=lambda: _counter(RadioRejection))
    radio_eligible: int = 0
    notebook_bytes: int = 0
    notebook_peak: int = 0
    notebook_inserted: int = 0
    notebook_deleted: int = 0
    notebook_revisions: int = 0
    notebook_rejected: dict[str, int] = field(default_factory=lambda: _counter(NotebookRejection))
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    requests: int = 0
    cost_usd: float | None = None


class MetricsTracker:
    def __init__(self, maze: MazeDefinition, initial: WorldState, rules: RulesConfig | None = None) -> None:
        to_exit = maze.path_lengths_from(maze.exit)  # undirected: also spawn -> exit
        self._rules = rules
        self._reachable = len(to_exit)
        self._oracle = max(to_exit[s] for s in maze.spawns)
        self._state = initial
        self._agents: dict[AgentId, _AgentTally] = {
            a.agent_id: _AgentTally(a.position, to_exit[a.position], {a.position}) for a in initial.agents
        }
        colocated = [self._colocated(initial, pair) for pair in PAIRS]
        self._colocated_ticks = [int(c) for c in colocated]
        self._episodes = [int(c) for c in colocated]

    @staticmethod
    def _colocated(state: WorldState, pair: tuple[AgentId, AgentId]) -> bool:
        return state.agent(pair[0]).position == state.agent(pair[1]).position

    def update(
        self, prev: WorldState, result: TickResult, usage: Mapping[AgentId, Usage] | None = None
    ) -> None:
        """Account for one committed tick `prev -> result.state`."""
        if prev != self._state or result.state.tick != prev.tick + 1:
            raise ValueError("ticks must be fed in order, starting from the initial state")
        new = result.state
        for agent_id, tally in self._agents.items():
            self._update_movement(tally, prev, new, agent_id)
            self._update_radio(tally, prev, new, agent_id)
            self._update_notebook(tally, prev, new, agent_id)
            if usage is not None and agent_id in usage:
                self._update_usage(tally, usage[agent_id])
        for event in result.events:
            if isinstance(event, NotebookUpdated):
                self._count_splice(self._agents[event.agent_id], prev, event)
        for i, pair in enumerate(PAIRS):
            now = self._colocated(new, pair)
            self._colocated_ticks[i] += now
            self._episodes[i] += now and not self._colocated(prev, pair)
        self._state = new

    def _update_movement(self, t: _AgentTally, prev: WorldState, new: WorldState, agent_id: AgentId) -> None:
        agent = new.agent(agent_id)
        movement = agent.last_receipt.movement
        match movement.outcome:
            case "moved":
                t.moves += 1
                t.revisits += agent.position in t.visited
                t.visited.add(agent.position)
            case "blocked":
                t.blocked += 1
            case "stayed":
                t.stayed += 1
            case _:
                assert movement.cause is not None
                t.forced_by_cause[movement.cause] += 1
        if prev.agent(agent_id).first_exit_tick is None and agent.first_exit_tick is not None:
            t.first_exit_tick = agent.first_exit_tick
            t.moves_to_first_exit = t.moves

    def _update_radio(self, t: _AgentTally, prev: WorldState, new: WorldState, agent_id: AgentId) -> None:
        rules = self._rules
        if rules is not None and rules.radio_enabled:
            t.radio_eligible += new.tick >= next_eligible_tick(
                prev.agent(agent_id).last_radio_tick, rules.radio_cooldown_ticks
            )
        receipt = new.agent(agent_id).last_receipt.radio
        if receipt.status == "rejected":
            assert receipt.code is not None
            t.radio_rejected[receipt.code] += 1
        for msg in new.radio_batch:
            if msg.sender == agent_id:
                t.radio_accepted += 1
                t.radio_bytes += utf8_len(msg.text)

    def _update_notebook(self, t: _AgentTally, prev: WorldState, new: WorldState, agent_id: AgentId) -> None:
        agent = new.agent(agent_id)
        receipt = agent.last_receipt.notebook
        if receipt.status == "rejected":
            assert receipt.code is not None
            t.notebook_rejected[receipt.code] += 1
        t.notebook_revisions = agent.notebook.revision
        t.notebook_bytes = agent.notebook.utf8_bytes
        t.notebook_peak = max(t.notebook_peak, t.notebook_bytes)

    @staticmethod
    def _count_splice(t: _AgentTally, prev: WorldState, event: NotebookUpdated) -> None:
        old_text = prev.agent(event.agent_id).notebook.text
        t.notebook_inserted += utf8_len(event.splice.text)
        t.notebook_deleted += utf8_len(old_text[event.splice.start : event.splice.end])

    @staticmethod
    def _update_usage(t: _AgentTally, usage: Usage) -> None:
        t.input_tokens = _add(t.input_tokens, usage.input_tokens)
        t.output_tokens = _add(t.output_tokens, usage.output_tokens)
        t.reasoning_tokens = _add(t.reasoning_tokens, usage.reasoning_tokens)
        t.requests += usage.requests
        t.cost_usd = _add(t.cost_usd, usage.estimated_cost_usd)

    def snapshot(self) -> RunMetrics:
        state = self._state
        visits = [t.visited for t in self._agents.values()]
        covered = set[Position]().union(*visits)
        shared = sum(1 for cell in covered if sum(cell in v for v in visits) >= 2)
        exits = [t.first_exit_tick for t in self._agents.values() if t.first_exit_tick is not None]
        return RunMetrics(
            tick=state.tick,
            objective_met_tick=state.objective_met_tick,
            first_exit_tick=min(exits, default=None),
            oracle_ticks=self._oracle,
            reachable_cells=self._reachable,
            covered_cells=len(covered),
            coverage=len(covered) / self._reachable,
            shared_cells=shared,
            redundant_exploration=shared / len(covered),
            meetings={
                f"{a}-{b}": PairMetrics(colocated_ticks=ticks, episodes=episodes)
                for (a, b), ticks, episodes in zip(PAIRS, self._colocated_ticks, self._episodes, strict=True)
            },
            agents={agent_id: self._agent_metrics(t) for agent_id, t in self._agents.items()},
        )

    def _agent_metrics(self, t: _AgentTally) -> AgentMetrics:
        forced = sum(t.forced_by_cause.values())
        cap = self._rules.notebook_cap_bytes if self._rules is not None else None
        return AgentMetrics(
            first_exit_tick=t.first_exit_tick,
            successful_moves=t.moves,
            blocked=t.blocked,
            stayed=t.stayed,
            forced_stays=forced,
            forced_stays_by_cause=dict(t.forced_by_cause),
            revisits=t.revisits,
            revisit_fraction=_ratio(t.revisits, t.moves),
            shortest_path_to_exit=t.shortest_path_to_exit,
            moves_to_first_exit=t.moves_to_first_exit,
            path_efficiency=_ratio(t.shortest_path_to_exit, t.moves_to_first_exit),
            scheduled_decisions=self._state.tick,
            valid_decisions=self._state.tick - forced,
            radio_accepted=t.radio_accepted,
            radio_bytes=t.radio_bytes,
            radio_rejected_by_code=dict(t.radio_rejected),
            radio_eligible_ticks=t.radio_eligible if self._rules is not None else None,
            notebook_bytes=t.notebook_bytes,
            notebook_peak_bytes=t.notebook_peak,
            notebook_inserted_bytes=t.notebook_inserted,
            notebook_deleted_bytes=t.notebook_deleted,
            notebook_revisions=t.notebook_revisions,
            notebook_rejected_by_code=dict(t.notebook_rejected),
            notebook_cap_bytes=cap,
            notebook_cap_pressure=_ratio(t.notebook_peak, cap),
            input_tokens=t.input_tokens,
            output_tokens=t.output_tokens,
            reasoning_tokens=t.reasoning_tokens,
            provider_requests=t.requests,
            estimated_cost_usd=t.cost_usd,
        )
