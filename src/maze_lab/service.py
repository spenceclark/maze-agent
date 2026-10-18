"""In-process run ownership, operator commands, and live event fan-out (spec §9.3, §11).

Framework-independent: the API layer calls into this, but simulations run as
their own asyncio tasks and keep going with no spectator connected.
One `RunService` per process owns every coordinator it starts.
"""

import asyncio
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from maze_lab.agent_contracts import AgentId
from maze_lab.config import RunConfig
from maze_lab.coordinator import TERMINAL, Coordinator, RunControl
from maze_lab.hashing import content_hash
from maze_lab.persistence.models import (
    CommandName,
    CommandReceipt,
    EventEnvelope,
    RunCommand,
    RunStatusChanged,
    RunSummary,
)
from maze_lab.persistence.store import RunStore
from maze_lab.policies.base import AgentPolicy
from maze_lab.runs import build_policies, create_run

log = logging.getLogger(__name__)


class ServiceError(Exception):
    status = 500
    code = "internal"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status, code = 404, "not_found"


class ConflictError(ServiceError):
    status, code = 409, "conflict"


class InvalidConfigError(ServiceError):
    status, code = 422, "invalid_configuration"


# ---- live fan-out -----------------------------------------------------------


@dataclass(eq=False)
class Subscription:
    run_id: str
    queue: asyncio.Queue[EventEnvelope | None] = field(default_factory=asyncio.Queue)
    queued_bytes: int = 0
    overflowed: bool = False


class EventHub:
    """Pushes committed events to subscribers. A lagging subscriber is cut off with a
    resync marker (None) instead of blocking the coordinator or dropping events silently."""

    def __init__(self, max_events: int = 1000, max_bytes: int = 8 * 1024 * 1024) -> None:
        self.max_events, self.max_bytes = max_events, max_bytes
        self._subs: dict[str, set[Subscription]] = {}

    def subscribe(self, run_id: str) -> Subscription:
        sub = Subscription(run_id)
        self._subs.setdefault(run_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.get(sub.run_id, set()).discard(sub)

    def publish(self, events: list[EventEnvelope]) -> None:
        if not events:
            return
        for sub in list(self._subs.get(events[0].run_id, ())):
            for event in events:
                size = len(event.model_dump_json())
                if sub.queue.qsize() >= self.max_events or sub.queued_bytes + size > self.max_bytes:
                    sub.overflowed = True
                    sub.queue.put_nowait(None)
                    self.unsubscribe(sub)
                    break
                sub.queued_bytes += size
                sub.queue.put_nowait(event)

    @staticmethod
    async def next(sub: Subscription) -> EventEnvelope | None:
        item = await sub.queue.get()
        if item is not None:
            sub.queued_bytes -= len(item.model_dump_json())
        return item


# ---- run ownership and commands ---------------------------------------------

_ALLOWED: dict[CommandName, tuple[str, ...]] = {
    "start": ("created",),
    "pause": ("running",),
    "resume": ("paused",),
    "step": ("paused",),
    "cancel": ("created", "running", "paused"),
}


class RunService:
    def __init__(self, store: RunStore, hub: EventHub) -> None:
        self.store, self.hub = store, hub
        self._tasks: dict[str, asyncio.Task[RunSummary]] = {}
        self._controls: dict[str, RunControl] = {}
        self._pending: dict[str, list[CommandReceipt]] = {}
        self.ready = False

    async def startup(self) -> None:
        """Re-adopt runs left running or paused by a previous process."""
        for summary in self.store.summaries():
            if summary.status in ("running", "paused"):
                self._launch(summary.run_id)
        self.ready = True

    async def shutdown(self) -> None:
        self.ready = False
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def summary(self, run_id: str) -> RunSummary:
        summary = self.store.summary(run_id)
        if summary is None:
            raise NotFoundError(f"no run {run_id}")
        return summary

    def create(self, config: RunConfig) -> RunSummary:
        try:
            build_policies(config)  # fail now on unknown providers or missing credentials
            return create_run(self.store, config)
        except ValueError as e:
            raise InvalidConfigError(str(e)) from e

    def pending_commands(self, run_id: str) -> list[CommandReceipt]:
        return list(self._pending.get(run_id, []))

    def command(self, run_id: str, cmd: RunCommand, idempotency_key: str) -> CommandReceipt:
        summary = self.summary(run_id)
        request_hash = content_hash(cmd)
        if (existing := self.store.command_by_key(run_id, idempotency_key)) is not None:
            if existing[0] != request_hash:
                raise ConflictError("idempotency key was already used with a different command")
            return existing[1]
        if cmd.expected_state_tick != summary.committed_tick:
            raise ConflictError(
                f"expected_state_tick {cmd.expected_state_tick} is stale; run is at {summary.committed_tick}"
            )
        if summary.status not in _ALLOWED[cmd.command]:
            raise ConflictError(f"cannot {cmd.command} a {summary.status} run")

        launch = cmd.command == "start" or run_id not in self._controls
        try:
            # Built before persisting the command, so a bad config fails cleanly.
            policies = build_policies(self.store.config(run_id), run_id) if launch else None
        except ValueError as e:
            raise InvalidConfigError(str(e)) from e

        open_tick = summary.status == "running"  # a tick may be in flight; it commits first
        receipt = CommandReceipt(
            command_id=uuid.uuid4().hex,
            run_id=run_id,
            command=cmd.command,
            status="pending",
            requested_at_tick=summary.committed_tick,
            effective_after_tick=summary.committed_tick + (1 if open_tick else 0),
            error=None,
        )
        self.store.save_command(receipt, idempotency_key, request_hash)
        self._pending.setdefault(run_id, []).append(receipt)

        control = self._launch(run_id, policies) if policies is not None else self._controls[run_id]
        if cmd.command == "start":
            return receipt
        match cmd.command:
            case "pause":
                control.pause()
            case "resume":
                control.resume()
            case "step":
                control.step()
            case "cancel":
                control.cancel()
        return receipt

    def _launch(self, run_id: str, policies: Mapping[AgentId, AgentPolicy] | None = None) -> RunControl:
        if run_id in self._controls:
            return self._controls[run_id]
        control = RunControl()
        coordinator = Coordinator(
            self.store,
            run_id,
            policies if policies is not None else build_policies(self.store.config(run_id), run_id),
            control=control,
            on_commit=lambda events: self._on_commit(run_id, events),
        )
        task = asyncio.create_task(coordinator.run(), name=f"run-{run_id}")
        task.add_done_callback(lambda t: self._finished(run_id, t))
        self._controls[run_id], self._tasks[run_id] = control, task
        return control

    def _finished(self, run_id: str, task: asyncio.Task[RunSummary]) -> None:
        self._tasks.pop(run_id, None)
        self._controls.pop(run_id, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            log.error("run %s failed", run_id, exc_info=error)

    def _on_commit(self, run_id: str, events: list[EventEnvelope]) -> None:
        self.hub.publish(events)
        for event in events:
            payload = event.payload
            if payload.type == "tick.committed":
                self._settle(run_id, "step", event.tick)
            elif isinstance(payload, RunStatusChanged):
                if payload.previous == "created":
                    self._settle(run_id, "start", event.tick)
                if payload.new == "paused" and payload.reason == "operator_pause":
                    self._settle(run_id, "pause", event.tick)
                if payload.new == "running" and payload.reason == "operator_resume":
                    self._settle(run_id, "resume", event.tick)
                if payload.new == "cancelled":
                    self._settle(run_id, "cancel", event.tick)
                if payload.new in TERMINAL:
                    for receipt in self._pending.pop(run_id, []):
                        self._update(receipt.model_copy(update={"status": "rejected", "error": "run ended"}))

    def _settle(self, run_id: str, command: CommandName, tick: int) -> None:
        pending = self._pending.get(run_id, [])
        for receipt in pending:
            if receipt.command == command:
                pending.remove(receipt)
                self._update(receipt.model_copy(update={"status": "applied", "effective_after_tick": tick}))
                return

    def _update(self, receipt: CommandReceipt) -> None:
        self.store.update_command(receipt)
