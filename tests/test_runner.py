"""Coordinator, persistence, and replay behaviour (spec §6.3, §9.3, §10, §17)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maze_lab.agent_contracts import AGENT_IDS, AgentId, AgentRules, Direction, Move, Observation, TurnAction
from maze_lab.config import RunConfig
from maze_lab.coordinator import Coordinator, RunControl
from maze_lab.domain.geometry import DIRECTIONS, Position
from maze_lab.domain.maze import MazeDefinition
from maze_lab.observation import observe
from maze_lab.persistence.models import InvocationRecord
from maze_lab.persistence.store import LostOwnershipError, RunStore
from maze_lab.policies.base import AgentPolicy, DecisionAttempt
from maze_lab.replay import export_run, verify_export, verify_run
from maze_lab.runs import build_policies, create_run


def make_config(policy: str = "dfs_bounded_v1", size: int = 6, **overrides: object) -> RunConfig:
    data: dict[str, object] = {
        "root_seed": 11,
        "condition": "test",
        "maze": {"width": size, "height": size},
        "agents": [{"id": a, "kind": "baseline", "policy": policy} for a in AGENT_IDS],
        "timing": {"mode": "barrier", "decision_window_ms": 5000},
        "horizon_ticks": 200,
    }
    data.update(overrides)
    return RunConfig.model_validate(data)


@pytest.fixture
def store(tmp_path: Path):
    s = RunStore(tmp_path / "runs.db")
    yield s
    s.close()


def stay(obs: Observation) -> DecisionAttempt:
    action = TurnAction(
        schema_version="1.0", tick=obs.decision_tick, move="STAY", notebook_edit=None, radio=None
    )
    return DecisionAttempt(action=action, failure=None)


class Sleeper:
    """Never answers within any reasonable deadline."""

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        await asyncio.sleep(3600)
        return stay(observation)


class Scripted:
    """Test-only policy that replays a fixed move list (it may know the maze; real policies may not)."""

    def __init__(self, moves: list[Move]) -> None:
        self.moves = moves

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        t = observation.decision_tick
        move: Move = self.moves[t - 1] if t <= len(self.moves) else "STAY"
        action = TurnAction(schema_version="1.0", tick=t, move=move, notebook_edit=None, radio=None)
        return DecisionAttempt(action=action, failure=None)


def shortest_moves(maze: MazeDefinition, start: Position) -> list[Direction]:
    dist = maze.path_lengths_from(maze.exit)
    moves: list[Direction] = []
    here = start
    while here != maze.exit:
        d: Direction = next(
            d for d in DIRECTIONS if maze.edge(here, d) == "open" and dist.get(here.step(d)) == dist[here] - 1
        )
        moves.append(d)
        here = here.step(d)
    return moves


def test_baseline_run_completes_and_replays(store: RunStore, tmp_path: Path):
    run_id = create_run(store, make_config()).run_id
    summary = asyncio.run(Coordinator(store, run_id, build_policies(store.config(run_id))).run())
    assert summary.status == "completed" and summary.termination_reason == "objective_met"
    final = store.tick_commit(run_id, summary.committed_tick)
    assert final is not None and all(a.first_exit_tick is not None for a in final.state.agents)

    report = verify_run(store, run_id)
    assert report.ok and report.ticks_checked == summary.committed_tick

    out = tmp_path / "run.zip"
    export_run(store, run_id, out)
    assert verify_export(out)

    sequences = [e.sequence for e in store.events(run_id)]
    assert sequences == list(range(1, len(sequences) + 1))
    assert [e.type for e in store.events(run_id)][-2:] == ["run.status_changed", "run.completed"]


def test_one_invocation_per_agent_per_tick(store: RunStore):
    run_id = create_run(store, make_config(horizon_ticks=5, policy="random_open_v1")).run_id
    asyncio.run(Coordinator(store, run_id, build_policies(store.config(run_id))).run())
    records = store.invocations(run_id)
    assert sorted((r.tick, r.agent_id) for r in records) == [(t, a) for t in range(1, 6) for a in AGENT_IDS]


def test_fixed_clock_advances_with_all_no_op_timeouts(store: RunStore):
    config = make_config(timing={"mode": "fixed_deadline", "decision_window_ms": 30}, horizon_ticks=3)
    run_id = create_run(store, config).run_id
    sleepers: dict[AgentId, AgentPolicy] = {a: Sleeper() for a in AGENT_IDS}
    summary = asyncio.run(Coordinator(store, run_id, sleepers).run())
    assert summary.committed_tick == 3 and summary.termination_reason == "tick_limit"
    final = store.tick_commit(run_id, 3)
    assert final is not None
    assert {a.last_receipt.movement.cause for a in final.state.agents} == {"timeout"}
    assert {r.status for r in store.invocations(run_id)} == {"timed_out"}


def test_late_result_never_mutates_a_later_tick(store: RunStore):
    class SlowEast:
        async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
            await asyncio.sleep(0.2)
            move: Move = "E" if observation.local.east == "open" else "STAY"
            return DecisionAttempt(
                action=TurnAction(
                    schema_version="1.0",
                    tick=observation.decision_tick,
                    move=move,
                    notebook_edit=None,
                    radio=None,
                ),
                failure=None,
            )

    config = make_config(timing={"mode": "barrier", "decision_window_ms": 20}, horizon_ticks=4)
    run_id = create_run(store, config).run_id
    asyncio.run(Coordinator(store, run_id, {a: SlowEast() for a in AGENT_IDS}).run())
    for t in range(1, 5):
        commit = store.tick_commit(run_id, t)
        assert commit is not None
        assert all(a.successful_moves == 0 for a in commit.state.agents)


def test_final_tick_success_beats_horizon(store: RunStore):
    probe = create_run(store, make_config(size=5), run_id="probe")
    maze = store.maze(probe.run_id)
    paths: dict[AgentId, list[Direction]] = {
        a: shortest_moves(maze, s) for a, s in zip(AGENT_IDS, maze.spawns, strict=True)
    }
    horizon = max(len(p) for p in paths.values())
    run_id = create_run(store, make_config(size=5, horizon_ticks=horizon)).run_id
    policies: dict[AgentId, AgentPolicy] = {a: Scripted(list(p)) for a, p in paths.items()}
    summary = asyncio.run(Coordinator(store, run_id, policies).run())
    assert summary.committed_tick == horizon and summary.termination_reason == "objective_met"


def test_manual_mode_steps_one_tick_then_cancel(store: RunStore):
    run_id = create_run(store, make_config(timing={"mode": "manual", "decision_window_ms": 1000})).run_id
    control = RunControl()

    async def scenario() -> None:
        coordinator = Coordinator(store, run_id, build_policies(store.config(run_id)), control=control)
        task = asyncio.create_task(coordinator.run())
        await asyncio.sleep(0.05)
        assert store.summary(run_id).status == "paused"  # type: ignore[union-attr]
        assert store.summary(run_id).committed_tick == 0  # type: ignore[union-attr]
        control.step()
        await asyncio.sleep(0.05)
        assert store.summary(run_id).committed_tick == 1  # type: ignore[union-attr]
        control.cancel()
        await task

    asyncio.run(scenario())
    summary = store.summary(run_id)
    assert (
        summary is not None
        and summary.status == "cancelled"
        and summary.termination_reason == "operator_cancelled"
    )


def test_stale_coordinator_is_fenced_out(store: RunStore):
    run_id = create_run(store, make_config()).run_id
    old = Coordinator(store, run_id, build_policies(store.config(run_id)))
    old.generation = store.acquire(run_id)
    old._load()
    store.acquire(run_id)  # a newer coordinator takes over
    with pytest.raises(LostOwnershipError):
        asyncio.run(old._play_tick())
    assert store.summary(run_id).committed_tick == 0  # type: ignore[union-attr]


def test_crash_with_open_tick_recovers_without_reissuing_calls(store: RunStore):
    run_id = create_run(store, make_config(horizon_ticks=3)).run_id
    config, maze = store.config(run_id), store.maze(run_id)
    genesis = store.tick_commit(run_id, 0)
    assert genesis is not None
    # A previous coordinator dispatched tick 1 and durably received only A's answer, then died.
    old_generation = store.acquire(run_id)
    for agent in AGENT_IDS:
        obs = observe(maze, config.rules, genesis.state, agent)
        attempt = stay(obs) if agent == "A" else None
        store.record_invocation(
            InvocationRecord(
                invocation_id=f"old:{agent}",
                run_id=run_id,
                agent_id=agent,
                tick=1,
                coordinator_generation=old_generation,
                status="completed" if attempt else "dispatched",
                observation=obs,
                observation_hash="x",
                rules=Coordinator(store, run_id, {}).agent_rules,
                attempt=attempt,
                dispatched_at=datetime.now(UTC),
                finished_at=None,
                duration_ms=None,
            )
        )

    class Forbidden:
        async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
            assert observation.decision_tick != 1, "tick 1 must not be re-invoked"
            return stay(observation)

    summary = asyncio.run(Coordinator(store, run_id, {a: Forbidden() for a in AGENT_IDS}).run())
    assert summary.recovered_incomplete_tick
    tick1 = store.tick_commit(run_id, 1)
    assert tick1 is not None
    causes = {a.agent_id: a.last_receipt.movement.cause for a in tick1.state.agents}
    assert causes == {"A": None, "B": "timeout", "C": "timeout"}
    assert verify_run(store, run_id).ok
