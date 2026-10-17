"""Response bodies for the spectator API. Every read names its run, tick, and journal position."""

from pydantic import BaseModel

from maze_lab.agent_contracts import Notebook, Observation
from maze_lab.config import RunConfig
from maze_lab.domain.state import AgentState
from maze_lab.metrics.tracker import RunMetrics
from maze_lab.persistence.models import CommandReceipt, RunManifest, RunSummary, TickSnapshot


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
    as_of_sequence: int


class RunDetail(BaseModel):
    summary: RunSummary
    config: RunConfig  # credentials are never stored, only environment variable names
    manifest: RunManifest
    commands: list[CommandReceipt]


class StateResponse(BaseModel):
    run_id: str
    state_tick: int
    as_of_sequence: int
    snapshot: TickSnapshot
    pending_commands: list[CommandReceipt]


class AgentsResponse(BaseModel):
    run_id: str
    state_tick: int
    as_of_sequence: int
    agents: list[AgentState]


class NotebookResponse(BaseModel):
    run_id: str
    state_tick: int
    as_of_sequence: int
    notebook: Notebook


class ObservationResponse(BaseModel):
    run_id: str
    decision_tick: int
    invocation_id: str
    observation: Observation


class MetricsResponse(BaseModel):
    run_id: str
    state_tick: int
    as_of_sequence: int
    metrics: RunMetrics


class ReplayResponse(BaseModel):
    run_id: str
    snapshot: TickSnapshot
    sequence_cursor: int  # subscribe or page the timeline after this to play forward
    manifest_schema_version: str
    available_ticks: tuple[int, int]


class Health(BaseModel):
    status: str
