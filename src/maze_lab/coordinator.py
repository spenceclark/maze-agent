"""The autonomous tick coordinator (spec §6.3, §9.2).

Owns time, concurrent dispatch, deadlines, and the atomic commit. It is the
only component that touches policies, the reducer, and the store together.
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Observation
from maze_lab.domain.events import DecisionResolved, GameEvent, NotebookUpdated, RadioSent
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.state import WorldState
from maze_lab.hashing import content_hash
from maze_lab.metrics.tracker import MetricsTracker
from maze_lab.observation import observe, public_rules
from maze_lab.persistence.models import (
    EventEnvelope,
    EventPayload,
    InvocationRecord,
    NotebookRevision,
    RadioRecord,
    RunCompleted,
    RunStatus,
    RunStatusChanged,
    RunSummary,
    TerminationReason,
    TickCommitted,
    TickSnapshot,
)
from maze_lab.persistence.store import CommitBatch, RunStore
from maze_lab.policies.base import AgentPolicy, DecisionAttempt, Usage
from maze_lab.replay import iter_committed_ticks

TERMINAL: tuple[RunStatus, ...] = ("completed", "cancelled", "failed")


def _now() -> datetime:
    return datetime.now(UTC)


class RunControl:
    """Operator controls, honoured only at tick boundaries."""

    def __init__(self) -> None:
        self.pause_requested = False
        self.cancel_requested = False
        self.steps_requested = 0
        self._wake = asyncio.Event()

    def pause(self) -> None:
        self.pause_requested = True

    def resume(self) -> None:
        self.pause_requested = False
        self._wake.set()

    def step(self) -> None:
        self.steps_requested += 1
        self._wake.set()

    def cancel(self) -> None:
        self.cancel_requested = True
        self._wake.set()

    async def wait(self) -> None:
        await self._wake.wait()
        self._wake.clear()


class Coordinator:
    def __init__(
        self,
        store: RunStore,
        run_id: str,
        policies: Mapping[AgentId, AgentPolicy],
        control: RunControl | None = None,
        on_commit: Callable[[list[EventEnvelope]], None] | None = None,
    ) -> None:
        self.store, self.run_id, self.policies = store, run_id, policies
        self.control = control or RunControl()
        self.on_commit = on_commit
        self.config = store.config(run_id)
        self.maze = store.maze(run_id)
        self.agent_rules = public_rules(self.config.rules)
        self.generation = 0
        self.sequence = 0
        self.status: RunStatus = "created"
        self.state: WorldState
        self.tracker: MetricsTracker

    # ---- lifecycle ----------------------------------------------------------

    async def run(self) -> RunSummary:
        """Drive the run until it reaches a terminal status."""
        self.generation = self.store.acquire(self.run_id)
        self._load()
        try:
            await self._recover_open_tick()
            if self.status == "paused" or self.config.timing.mode == "manual":
                self.control.pause_requested = True  # stays paused until an explicit resume
            if self.status == "created":
                new: RunStatus = "paused" if self.control.pause_requested else "running"
                self._transition(new, "started", started=True)
            while self.status not in TERMINAL:
                await self._loop_once()
        except Exception:
            if self.status not in TERMINAL:
                self._finish("failed", "infrastructure_failure")
            raise
        summary = self.store.summary(self.run_id)
        assert summary is not None
        return summary

    async def _loop_once(self) -> None:
        if self.control.cancel_requested:
            self._finish("cancelled", "operator_cancelled")
            return
        if self.status == "running" and self.control.pause_requested:
            self._transition("paused", "operator_pause")
            return
        if self.status == "paused":
            if self.control.steps_requested:
                self.control.steps_requested -= 1
                await self._play_tick()  # a step resolves exactly one tick and stays paused
            elif self.control.pause_requested:
                await self.control.wait()
            else:
                self._transition("running", "operator_resume")
            return
        await self._play_tick()

    def _load(self) -> None:
        summary = self.store.summary(self.run_id)
        if summary is None:
            raise KeyError(self.run_id)
        self.status = summary.status
        self.sequence = self.store.last_sequence(self.run_id)
        genesis = self.store.tick_commit(self.run_id, 0)
        assert genesis is not None
        self.state = genesis.state
        self.tracker = MetricsTracker(self.maze, genesis.state, self.config.rules)
        for tick in iter_committed_ticks(self.store, self.run_id):
            self.tracker.update(tick.prev, tick.result, tick.usage)
            self.state = tick.commit.state

    # ---- one tick -----------------------------------------------------------

    async def _play_tick(self) -> None:
        tick = self.state.tick + 1
        observations = {a: observe(self.maze, self.config.rules, self.state, a) for a in AGENT_IDS}
        records = {a: self._dispatch_record(a, tick, observations[a]) for a in AGENT_IDS}
        for record in records.values():
            self.store.record_invocation(record)

        window = self.config.timing.decision_window_ms / 1000
        opened = time.monotonic()
        tasks: dict[AgentId, asyncio.Task[tuple[DecisionAttempt, float]]] = {
            a: asyncio.create_task(self._invoke(a, observations[a])) for a in AGENT_IDS
        }
        _, pending = await asyncio.wait(tasks.values(), timeout=window)
        for task in pending:
            task.cancel()  # late results are never applied to any tick
        if self.config.timing.mode == "fixed_deadline":
            await asyncio.sleep(max(0.0, opened + window - time.monotonic()))

        attempts: dict[AgentId, DecisionAttempt] = {}
        for agent, task in tasks.items():
            attempt, finished = self._outcome(task, opened)
            attempts[agent] = attempt
            status = "timed_out" if task in pending else "completed" if attempt.action else "failed"
            self.store.record_invocation(
                records[agent].model_copy(
                    update={
                        "status": status,
                        "attempt": attempt,
                        "finished_at": _now(),
                        "duration_ms": None if finished is None else (finished - opened) * 1000,
                    }
                )
            )
        submissions: dict[AgentId, Submission] = {
            a: Submission(action=att.action, failure=att.failure, invocation_id=records[a].invocation_id)
            for a, att in attempts.items()
        }
        self._commit_tick(submissions, {a: att.usage for a, att in attempts.items()})

    async def _invoke(self, agent: AgentId, observation: Observation) -> tuple[DecisionAttempt, float]:
        attempt = await self.policies[agent].decide(observation, self.agent_rules)
        return attempt, time.monotonic()

    @staticmethod
    def _outcome(
        task: asyncio.Task[tuple[DecisionAttempt, float]], opened: float
    ) -> tuple[DecisionAttempt, float | None]:
        if not task.done() or task.cancelled():
            return DecisionAttempt(action=None, failure="timeout"), None
        if (error := task.exception()) is not None:
            detail = f"{type(error).__name__}: {error}"
            return DecisionAttempt(action=None, failure="provider_error", error_detail=detail), None
        return task.result()

    def _dispatch_record(self, agent: AgentId, tick: int, observation: Observation) -> InvocationRecord:
        return InvocationRecord(
            invocation_id=f"{self.run_id}:{tick}:{agent}:g{self.generation}",
            run_id=self.run_id,
            agent_id=agent,
            tick=tick,
            coordinator_generation=self.generation,
            status="dispatched",
            observation=observation,
            observation_hash=content_hash(observation),
            rules=self.agent_rules,
            attempt=None,
            dispatched_at=_now(),
            finished_at=None,
            duration_ms=None,
        )

    async def _recover_open_tick(self) -> None:
        """Resolve a tick a crashed coordinator dispatched but never committed (spec §9.3).

        Durably recorded results are used; anything unresolved becomes a forced
        no-op. Provider calls are never reissued. The run leaves the strict cohort.
        """
        tick = self.state.tick + 1
        records = self.store.invocations(self.run_id, tick=tick)
        if not records or self.status in TERMINAL:
            return
        submissions: dict[AgentId, Submission] = {}
        usage: dict[AgentId, Usage] = {}
        for rec in records:
            if rec.status in ("completed", "failed") and rec.attempt is not None:
                att = rec.attempt
                submissions[rec.agent_id] = Submission(
                    action=att.action, failure=att.failure, invocation_id=rec.invocation_id
                )
                usage[rec.agent_id] = att.usage
            else:
                submissions[rec.agent_id] = Submission(
                    action=None, failure="timeout", invocation_id=rec.invocation_id
                )
        self._commit_tick(submissions, usage, recovered=True)

    def _commit_tick(
        self, submissions: dict[AgentId, Submission], usage: dict[AgentId, Usage], recovered: bool = False
    ) -> None:
        prev = self.state
        result = resolve(self.maze, self.config.rules, prev, submissions)
        self.tracker.update(prev, result, usage)
        tick, state, metrics = result.state.tick, result.state, self.tracker.snapshot()
        state_hash = content_hash(state)
        first = self.sequence + 1

        envelopes = [self._envelope(tick, e) for e in result.events]
        commit = TickCommitted(
            state=state,
            metrics=metrics,
            state_hash=state_hash,
            first_sequence=first,
            last_sequence=self.sequence + 1,
        )
        envelopes.append(self._envelope(tick, commit))

        reason = self._termination(state)
        batch = CommitBatch(
            events=envelopes,
            committed_tick=tick,
            recovered_incomplete_tick=True if recovered else None,
            notebook_revisions=self._notebook_revisions(tick, result.events),
            radio=self._radio_records(envelopes),
            decisions=[
                (e.agent_id, tick, e.invocation_id) for e in result.events if isinstance(e, DecisionResolved)
            ],
        )
        if reason is not None or tick % self.config.snapshot_interval_ticks == 0:
            batch.snapshot = TickSnapshot(
                run_id=self.run_id,
                tick=tick,
                last_sequence=self.sequence,
                maze_hash=self.maze.maze_hash,
                state=state,
                metrics=metrics,
                state_hash=state_hash,
            )
        if reason is not None:
            self._append_terminal(batch, "completed", reason, tick)
        self.store.commit(self.run_id, self.generation, batch)
        self.state = state
        if reason is not None:
            self.status = "completed"
        self._publish(batch.events)

    def _termination(self, state: WorldState) -> TerminationReason | None:
        if state.objective_met_tick is not None:
            return "objective_met"  # success wins over the horizon on the same tick
        if state.tick >= self.config.horizon_ticks:
            return "tick_limit"
        return None

    # ---- status changes -----------------------------------------------------

    def _transition(self, new: RunStatus, reason: str, started: bool = False) -> None:
        event = RunStatusChanged(previous=self.status, new=new, reason=reason, effective_tick=self.state.tick)
        batch = CommitBatch(
            events=[self._envelope(self.state.tick, event)],
            status=new,
            started_at=_now() if started else None,
        )
        self.store.commit(self.run_id, self.generation, batch)
        self.status = new
        self._publish(batch.events)

    def _finish(self, status: RunStatus, reason: TerminationReason) -> None:
        batch = CommitBatch(events=[])
        self._append_terminal(batch, status, reason, self.state.tick)
        self.store.commit(self.run_id, self.generation, batch)
        self.status = status
        self._publish(batch.events)

    def _append_terminal(
        self, batch: CommitBatch, status: RunStatus, reason: TerminationReason, tick: int
    ) -> None:
        changed = RunStatusChanged(previous=self.status, new=status, reason=reason, effective_tick=tick)
        completed = RunCompleted(
            reason=reason, metrics=self.tracker.snapshot(), final_state_hash=content_hash(self.state)
        )
        if batch.committed_tick is not None:  # terminal tick: hash the state being committed
            committed = batch.events[-1].payload
            assert isinstance(committed, TickCommitted)
            completed = completed.model_copy(update={"final_state_hash": committed.state_hash})
        batch.events += [self._envelope(tick, changed), self._envelope(tick, completed)]
        batch.status, batch.termination_reason, batch.ended_at = status, reason, _now()

    # ---- journal helpers ----------------------------------------------------

    def _envelope(self, tick: int, payload: EventPayload) -> EventEnvelope:
        self.sequence += 1
        return EventEnvelope(
            run_id=self.run_id,
            sequence=self.sequence,
            tick=tick,
            type=payload.type,
            recorded_at=_now(),
            payload=payload,
        )

    def _notebook_revisions(self, tick: int, events: list[GameEvent]) -> list[NotebookRevision]:
        return [
            NotebookRevision(
                run_id=self.run_id,
                agent_id=e.agent_id,
                revision=e.new_revision,
                tick=tick,
                splice=e.splice,
                text=e.text,
                utf8_bytes=len(e.text.encode()),
                sha256=e.sha256,
            )
            for e in events
            if isinstance(e, NotebookUpdated)
        ]

    def _radio_records(self, envelopes: list[EventEnvelope]) -> list[RadioRecord]:
        return [
            RadioRecord(
                run_id=self.run_id,
                sequence=env.sequence,
                sender=p.sender,
                sent_tick=p.sent_tick,
                visible_decision_tick=p.visible_decision_tick,
                recipients=p.recipients,
                text=p.text,
                utf8_bytes=p.utf8_bytes,
            )
            for env in envelopes
            if isinstance(p := env.payload, RadioSent)
        ]

    def _publish(self, events: list[EventEnvelope]) -> None:
        if self.on_commit is not None:
            self.on_commit(events)
