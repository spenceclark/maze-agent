"""Spectator-side records and the event journal envelope (spec §8, §10).

None of these are ever shown to an agent.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from maze_lab.agent_contracts import (
    AgentId,
    AgentRules,
    Contract,
    NotebookEdit,
    Observation,
)
from maze_lab.config import RunConfig
from maze_lab.domain.events import (
    DecisionResolved,
    ExitReached,
    MeetingObserved,
    NotebookUpdated,
    RadioSent,
)
from maze_lab.domain.state import WorldState
from maze_lab.metrics.tracker import RunMetrics
from maze_lab.policies.base import DecisionAttempt

RunStatus = Literal["created", "running", "paused", "completed", "cancelled", "failed"]
TerminationReason = Literal[
    "objective_met", "tick_limit", "resource_limit", "operator_cancelled", "infrastructure_failure"
]


class RunCreated(Contract):
    type: Literal["run.created"] = "run.created"
    manifest_hash: str
    initial_state_hash: str


class RunStatusChanged(Contract):
    type: Literal["run.status_changed"] = "run.status_changed"
    previous: RunStatus
    new: RunStatus
    reason: str | None
    effective_tick: int


class TickCommitted(Contract):
    type: Literal["tick.committed"] = "tick.committed"
    state: WorldState
    metrics: RunMetrics
    state_hash: str
    first_sequence: int  # this tick's event range, inclusive of this event
    last_sequence: int


class RunCompleted(Contract):
    type: Literal["run.completed"] = "run.completed"
    reason: TerminationReason
    metrics: RunMetrics
    final_state_hash: str


EventPayload = Annotated[
    RunCreated
    | RunStatusChanged
    | DecisionResolved
    | NotebookUpdated
    | RadioSent
    | MeetingObserved
    | ExitReached
    | TickCommitted
    | RunCompleted,
    Field(discriminator="type"),
]


class EventEnvelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    sequence: int = Field(ge=1)
    tick: int = Field(ge=0)
    type: str
    recorded_at: datetime
    payload: EventPayload


class RunSummary(Contract):
    run_id: str
    status: RunStatus
    committed_tick: int
    config_hash: str
    maze_hash: str
    condition: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    termination_reason: TerminationReason | None
    recovered_incomplete_tick: bool  # True excludes the run from the strict benchmark cohort


class RunManifest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    config: RunConfig
    config_hash: str
    maze_hash: str
    initial_state_hash: str
    dependency_lock_hash: str | None
    python_version: str
    platform: str
    code_commit: str | None
    versions: dict[str, str]  # generator, prng, sampler, reducer, rules, prompt, metrics
    randomness: str  # how streams derive from the root seed


class TickSnapshot(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    tick: int
    last_sequence: int
    maze_hash: str
    state: WorldState
    metrics: RunMetrics
    state_hash: str


class NotebookRevision(Contract):
    run_id: str
    agent_id: AgentId
    revision: int
    tick: int
    splice: NotebookEdit
    text: str
    utf8_bytes: int
    sha256: str


class RadioRecord(Contract):
    run_id: str
    sequence: int
    sender: AgentId
    sent_tick: int
    visible_decision_tick: int
    recipients: list[AgentId]
    text: str
    utf8_bytes: int


InvocationStatus = Literal["dispatched", "completed", "failed", "timed_out"]


class InvocationRecord(Contract):
    """Ledger entry for one policy invocation. Written outside the tick transaction."""

    invocation_id: str
    run_id: str
    agent_id: AgentId
    tick: int
    coordinator_generation: int
    status: InvocationStatus
    observation: Observation
    observation_hash: str
    rules: AgentRules
    attempt: DecisionAttempt | None
    dispatched_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
