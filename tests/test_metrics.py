"""Metrics tracker on tiny hand-built runs with hand-computed expectations."""

import pytest
from helpers import RULES, P, act, grid, step

from maze_lab.agent_contracts import AgentId, Move
from maze_lab.config import RulesConfig
from maze_lab.domain.maze import MazeDefinition
from maze_lab.domain.reducer import Submission, TickResult
from maze_lab.domain.state import initial_state
from maze_lab.metrics.tracker import MetricsTracker, RunMetrics
from maze_lab.policies.base import Usage

# 3x3 open grid. Exit bottom-right; A top-left, B top-middle, C middle-left.
OPEN = grid(3, 3, exit=P(2, 2), spawns=[P(0, 0), P(1, 0), P(0, 1)])

# 2x2 with a wall east of A: only (0,0)S, (0,1)E, (1,0)S are open.
WALLED = grid(
    2, 2, P(1, 1), [P(0, 0), P(1, 0), P(0, 1)], open_edges=[(P(0, 0), "S"), (P(0, 1), "E"), (P(1, 0), "S")]
)

Tick = dict[str, Submission]


def play(
    maze: MazeDefinition, ticks: list[Tick], step_rules: RulesConfig = RULES
) -> tuple[MetricsTracker, list[TickResult]]:
    state = initial_state(maze)
    tracker = MetricsTracker(maze, state, RULES)
    results = []
    for subs in ticks:
        result = step(maze, state, step_rules, **subs)
        tracker.update(state, result)
        results.append(result)
        state = result.state
    return tracker, results


def moves(agent: str, *dirs: Move) -> list[Tick]:
    return [{agent: act(t, d)} for t, d in enumerate(dirs, start=1)]


def test_initial_snapshot_counts_spawns():
    m = MetricsTracker(OPEN, initial_state(OPEN), RULES).snapshot()
    assert (m.tick, m.covered_cells, m.reachable_cells, m.coverage) == (0, 3, 9, 3 / 9)
    assert (m.shared_cells, m.redundant_exploration) == (0, 0.0)
    assert m.oracle_ticks == 4  # A at (0,0) is 4 steps from (2,2)
    assert m.first_exit_tick is None and m.objective_met_tick is None
    a = m.agents["A"]
    assert (a.successful_moves, a.revisit_fraction, a.path_efficiency) == (0, None, None)
    assert (a.scheduled_decisions, a.valid_decisions) == (0, 0)
    assert list(m.agents) == ["A", "B", "C"] and list(m.meetings) == ["A-B", "A-C", "B-C"]


def test_revisits_and_redundant_exploration():
    # A: E onto B's spawn (new for A), W back to own spawn (revisit), E again (revisit).
    tracker, _ = play(OPEN, moves("A", "E", "W", "E"))
    m = tracker.snapshot()
    a = m.agents["A"]
    assert (a.successful_moves, a.revisits, a.revisit_fraction) == (3, 2, 2 / 3)
    assert (m.covered_cells, m.shared_cells, m.redundant_exploration) == (3, 1, 1 / 3)
    assert m.agents["B"].revisit_fraction is None


def test_path_efficiency_only_for_finishers():
    # A detours S,N before the 4-step route: 6 moves to exit at tick 6.
    tracker, _ = play(OPEN, moves("A", "S", "N", "E", "E", "S", "S"))
    m = tracker.snapshot()
    a, b = m.agents["A"], m.agents["B"]
    assert (a.first_exit_tick, a.moves_to_first_exit, a.shortest_path_to_exit) == (6, 6, 4)
    assert a.path_efficiency == 4 / 6
    assert b.path_efficiency is None and b.moves_to_first_exit is None
    assert m.first_exit_tick == 6 and m.objective_met_tick is None
    # Spawns plus (2,0), (2,1), (2,2); A crossed both C's and B's spawn.
    assert (m.covered_cells, m.shared_cells, a.revisits) == (6, 2, 1)


def test_meeting_episodes():
    # Tick 1: adjacent A and B swap cells, which is not a meeting.
    # Tick 2: B walks onto staying A (meet); tick 3 A leaves; tick 4 A comes back (meet).
    ticks: list[Tick] = [
        {"A": act(1, "E"), "B": act(1, "W")},
        {"B": act(2, "E")},
        {"A": act(3, "E")},
        {"A": act(4, "W")},
    ]
    tracker, results = play(OPEN, ticks)
    assert results[0].state.agent("A").position == P(1, 0) and results[0].state.meetings == []
    assert results[-1].state.agent("A").position == P(1, 0)
    m = tracker.snapshot().meetings
    assert (m["A-B"].colocated_ticks, m["A-B"].episodes) == (2, 2)
    assert (m["A-C"].colocated_ticks, m["B-C"].episodes) == (0, 0)


def test_movement_failures_reported_separately():
    timeout = Submission(action=None, failure="timeout")
    ticks: list[Tick] = [
        {"A": act(1, "E"), "C": timeout},  # A blocked by wall, B stays, C times out
        {"A": act(1, "S"), "B": act(2, "S")},  # A stale tick, B moves
    ]
    tracker, _ = play(WALLED, ticks)
    no_stay, _ = play(WALLED, [{}], step_rules=RulesConfig(allow_stay=False))

    m = tracker.snapshot().agents
    assert (m["A"].blocked, m["A"].stayed, m["A"].forced_stays) == (1, 0, 1)
    assert m["A"].forced_stays_by_cause["stale_tick"] == 1
    assert (m["B"].blocked, m["B"].stayed, m["B"].successful_moves) == (0, 1, 1)
    assert (m["C"].forced_stays_by_cause["timeout"], m["C"].stayed) == (1, 1)
    assert (m["A"].scheduled_decisions, m["A"].valid_decisions) == (2, 1)
    assert (m["B"].valid_decisions, m["C"].valid_decisions) == (2, 1)
    stay_disabled = no_stay.snapshot().agents["A"]
    assert stay_disabled.forced_stays_by_cause["stay_disabled"] == 1 and stay_disabled.stayed == 0


def test_radio_rejections_by_code_and_eligibility():
    ticks: list[Tick] = [
        {"A": act(1, radio="hi"), "B": act(1, radio="  ")},
        {"A": act(2, radio="again"), "B": act(2, radio="x" * 281)},
        {"A": act(3, radio="more")},
    ]
    tracker, _ = play(OPEN, ticks)
    a, b = tracker.snapshot().agents["A"], tracker.snapshot().agents["B"]
    assert (a.radio_accepted, a.radio_bytes, a.radio_rejected_by_code["radio_cooldown"]) == (1, 2, 2)
    assert a.radio_eligible_ticks == 1  # sent tick 1; cooldown 5 blocks ticks 2-6
    assert b.radio_accepted == 0 and b.radio_eligible_ticks == 3
    assert b.radio_rejected_by_code["empty_radio"] == 1
    assert b.radio_rejected_by_code["radio_budget_exceeded"] == 1


def test_notebook_bytes():
    ticks: list[Tick] = [
        {"A": act(1, edit=(0, 0, 0, "héllo"))},  # 6 bytes inserted
        {"A": act(2, edit=(1, 0, 2, ""))},  # delete "hé": 3 bytes
        {"A": act(3, edit=(0, 0, 0, "x"))},  # stale revision
    ]
    tracker, _ = play(OPEN, ticks)
    a = tracker.snapshot().agents["A"]
    assert (a.notebook_inserted_bytes, a.notebook_deleted_bytes) == (6, 3)
    assert (a.notebook_bytes, a.notebook_peak_bytes, a.notebook_revisions) == (3, 6, 2)
    assert a.notebook_rejected_by_code["stale_revision"] == 1
    assert a.notebook_cap_pressure == 6 / 8192


def test_replay_rebuilds_identical_snapshot():
    ticks: list[Tick] = [
        {"A": act(1, "E", edit=(0, 0, 0, "n"), radio="r"), "C": act(1, "S")},
        {"A": act(2, "S"), "B": act(2, "W")},
        {"A": act(3, "S"), "C": Submission(action=None, failure="provider_error")},
    ]
    _, results = play(OPEN, ticks)
    usage: dict[AgentId, Usage] = {"A": Usage(input_tokens=10, requests=1)}

    def rebuild() -> RunMetrics:
        state = initial_state(OPEN)
        tracker = MetricsTracker(OPEN, state, RULES)
        for result in results:
            tracker.update(state, result, usage)
            state = result.state
        return tracker.snapshot()

    first = rebuild()
    assert first == rebuild()
    assert (first.agents["A"].input_tokens, first.agents["A"].provider_requests) == (30, 3)
    assert first.agents["A"].output_tokens is None and first.agents["B"].input_tokens is None


def test_out_of_order_update_rejected():
    tracker, results = play(OPEN, [{}, {}])
    with pytest.raises(ValueError):
        tracker.update(results[0].state, results[1])
