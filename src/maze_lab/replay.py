"""Playback and deterministic re-execution (spec §10)."""

from collections.abc import Iterator
from dataclasses import dataclass

from maze_lab.agent_contracts import AgentId
from maze_lab.domain.events import DecisionResolved, GameEvent
from maze_lab.domain.reducer import Submission, TickResult, resolve
from maze_lab.domain.state import WorldState, initial_state
from maze_lab.hashing import content_hash
from maze_lab.persistence.models import TickCommitted
from maze_lab.persistence.store import RunStore
from maze_lab.policies.base import Usage


@dataclass(frozen=True)
class CommittedTick:
    """One recorded tick: the state before, what happened, and the committed result."""

    tick: int
    prev: WorldState
    events: list[GameEvent]
    commit: TickCommitted
    usage: dict[AgentId, Usage]

    @property
    def result(self) -> TickResult:
        return TickResult(self.commit.state, self.events)


def iter_committed_ticks(store: RunStore, run_id: str) -> Iterator[CommittedTick]:
    """Playback from the journal alone: zero policy or provider calls."""
    usage: dict[int, dict[AgentId, Usage]] = {}
    for inv in store.invocations(run_id):
        if inv.attempt is not None:
            usage.setdefault(inv.tick, {})[inv.agent_id] = inv.attempt.usage

    prev: WorldState | None = None
    pending: list[GameEvent] = []
    for envelope in store.events(run_id):
        payload = envelope.payload
        if isinstance(payload, TickCommitted):
            if prev is not None:
                yield CommittedTick(envelope.tick, prev, pending, payload, usage.get(envelope.tick, {}))
            prev, pending = payload.state, []
        elif payload.type in ("run.created", "run.status_changed", "run.completed"):
            continue
        else:
            pending.append(payload)  # pyright: ignore[reportArgumentType]


def submission_from(decision: DecisionResolved) -> Submission:
    """Rebuild what the reducer was given from the recorded decision."""
    if decision.action is not None:
        return Submission(action=decision.action, failure=None, invocation_id=decision.invocation_id)
    cause = decision.receipt.movement.cause
    assert cause in ("timeout", "provider_error", "refusal", "invalid_action", "stale_tick", "stay_disabled")
    return Submission(action=None, failure=cause, invocation_id=decision.invocation_id)


@dataclass(frozen=True)
class VerifyReport:
    ticks_checked: int
    mismatched_ticks: list[int]

    @property
    def ok(self) -> bool:
        return not self.mismatched_ticks


def verify_run(store: RunStore, run_id: str) -> VerifyReport:
    """Re-execute recorded actions through the reducer and compare every state hash."""
    config, maze = store.config(run_id), store.maze(run_id)
    state = initial_state(maze)
    mismatched: list[int] = []
    genesis = store.tick_commit(run_id, 0)
    if genesis is None or genesis.state_hash != content_hash(state):
        mismatched.append(0)
    checked = 0
    for tick in iter_committed_ticks(store, run_id):
        decisions = [e for e in tick.events if isinstance(e, DecisionResolved)]
        result = resolve(maze, config.rules, state, {d.agent_id: submission_from(d) for d in decisions})
        if content_hash(result.state) != tick.commit.state_hash or result.events != tick.events:
            mismatched.append(tick.tick)
        state = result.state
        checked += 1
    return VerifyReport(checked, mismatched)
