"""REST endpoints (spec §11.2). Reads are spectator-only; mutations need the operator role."""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from maze_lab.agent_contracts import AgentId
from maze_lab.api.common import (
    ApiError,
    ReadPoint,
    Service,
    Store,
    decode_cursor,
    encode_cursor,
    page_limit,
    read_point,
    require,
)
from maze_lab.api.schemas import (
    AgentsResponse,
    MetricsResponse,
    NotebookResponse,
    ObservationResponse,
    Page,
    ReplayResponse,
    RunDetail,
    StateResponse,
)
from maze_lab.config import RunConfig
from maze_lab.domain.maze import MazeDefinition
from maze_lab.persistence.models import (
    CommandReceipt,
    EventEnvelope,
    InvocationRecord,
    NotebookRevision,
    RadioRecord,
    RunCommand,
    RunStatus,
    RunSummary,
    TickCommitted,
    TickSnapshot,
)
from maze_lab.persistence.store import RunStore
from maze_lab.replay import export_run

router = APIRouter(prefix="/api/v1")
spectator = [require("spectator")]
operator = [require("operator")]

AtTick = Annotated[int | None, Query(ge=0)]
Limit = Annotated[int | None, Query()]


def _page[T](
    items: list[T], cursor: str | None, limit: int | None, filters: dict[str, object], as_of: int
) -> Page[T]:
    size = page_limit(limit)
    offset, _ = decode_cursor(cursor, filters, as_of)
    chunk = items[offset : offset + size]
    more = offset + size < len(items)
    return Page[T](
        items=chunk,
        next_cursor=encode_cursor(offset + size, filters, as_of) if more else None,
        as_of_sequence=as_of,
    )


def _commit(store: RunStore, point: ReadPoint) -> TickCommitted:
    commit = store.tick_commit(point.run_id, point.state_tick)
    assert commit is not None  # read_point already checked
    return commit


def _snapshot(store: RunStore, point: ReadPoint) -> TickSnapshot:
    commit = _commit(store, point)
    return TickSnapshot(
        run_id=point.run_id,
        tick=point.state_tick,
        last_sequence=commit.last_sequence,
        maze_hash=store.maze(point.run_id).maze_hash,
        state=commit.state,
        metrics=commit.metrics,
        state_hash=commit.state_hash,
    )


def _cursor_point(store: RunStore, run_id: str, cursor: str | None, filters: dict[str, object]) -> int:
    """The as_of_sequence a paged read is pinned to: the cursor's, or now."""
    now = read_point(store, run_id).as_of_sequence
    return decode_cursor(cursor, filters, now)[1]


# ---- runs -------------------------------------------------------------------


@router.post("/runs", status_code=201, dependencies=operator)
def create_run(config: RunConfig, service: Service) -> RunSummary:
    return service.create(config)


@router.get("/runs", dependencies=spectator)
def list_runs(
    store: Store,
    status: RunStatus | None = None,
    condition: str | None = None,
    cursor: str | None = None,
    limit: Limit = None,
) -> Page[RunSummary]:
    filters: dict[str, object] = {"status": status, "condition": condition}
    runs = store.summaries(status=status, condition=condition)
    return _page(runs, cursor, limit, filters, as_of=0)  # runs are not journal events


@router.get("/runs/{run_id}", dependencies=spectator)
def get_run(run_id: str, store: Store, service: Service) -> RunDetail:
    summary = service.summary(run_id)
    return RunDetail(
        summary=summary,
        config=store.config(run_id),
        manifest=store.manifest(run_id),
        commands=store.commands(run_id),
    )


@router.post("/runs/{run_id}/commands", status_code=202, dependencies=operator)
async def run_command(  # async: starting a coordinator needs the server's event loop
    run_id: str,
    command: RunCommand,
    service: Service,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
) -> CommandReceipt:
    return service.command(run_id, command, idempotency_key)


@router.get("/runs/{run_id}/maze", dependencies=spectator, response_model=MazeDefinition)
def get_maze(
    run_id: str, store: Store, response: Response, if_none_match: Annotated[str | None, Header()] = None
) -> MazeDefinition | Response:
    read_point(store, run_id)
    maze = store.maze(run_id)
    etag = f'"{maze.maze_hash}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return maze


# ---- state at a tick --------------------------------------------------------


@router.get("/runs/{run_id}/state", dependencies=spectator)
def get_state(run_id: str, store: Store, service: Service, at_tick: AtTick = None) -> StateResponse:
    point = read_point(store, run_id, at_tick)
    return StateResponse(
        **point.model_dump(),
        snapshot=_snapshot(store, point),
        pending_commands=service.pending_commands(run_id),
    )


@router.get("/runs/{run_id}/agents", dependencies=spectator)
def get_agents(run_id: str, store: Store, at_tick: AtTick = None) -> AgentsResponse:
    point = read_point(store, run_id, at_tick)
    return AgentsResponse(**point.model_dump(), agents=_commit(store, point).state.agents)


@router.get("/runs/{run_id}/agents/{agent_id}/notebook", dependencies=spectator)
def get_notebook(run_id: str, agent_id: AgentId, store: Store, at_tick: AtTick = None) -> NotebookResponse:
    point = read_point(store, run_id, at_tick)
    return NotebookResponse(
        **point.model_dump(), notebook=_commit(store, point).state.agent(agent_id).notebook
    )


@router.get("/runs/{run_id}/agents/{agent_id}/observation", dependencies=spectator)
def get_observation(
    run_id: str, agent_id: AgentId, store: Store, decision_tick: Annotated[int, Query(ge=1)]
) -> ObservationResponse:
    read_point(store, run_id)
    records = store.invocations(run_id, tick=decision_tick, agent_id=agent_id)
    if not records:
        raise ApiError(
            404, "not_found", f"no recorded observation for {agent_id} at decision tick {decision_tick}"
        )
    record = max(records, key=lambda r: r.coordinator_generation)
    return ObservationResponse(
        run_id=run_id,
        decision_tick=decision_tick,
        invocation_id=record.invocation_id,
        observation=record.observation,
    )


@router.get("/runs/{run_id}/metrics", dependencies=spectator)
def get_metrics(run_id: str, store: Store, at_tick: AtTick = None) -> MetricsResponse:
    point = read_point(store, run_id, at_tick)
    return MetricsResponse(**point.model_dump(), metrics=_commit(store, point).metrics)


@router.get("/runs/{run_id}/replay", dependencies=spectator)
def get_replay(run_id: str, store: Store, at_tick: Annotated[int, Query(ge=0)]) -> ReplayResponse:
    snapshot = _snapshot(store, read_point(store, run_id, at_tick))
    latest = read_point(store, run_id).state_tick
    return ReplayResponse(
        run_id=run_id,
        snapshot=snapshot,
        sequence_cursor=snapshot.last_sequence,
        manifest_schema_version=store.manifest(run_id).schema_version,
        available_ticks=(0, latest),
    )


# ---- append-only collections ------------------------------------------------


@router.get("/runs/{run_id}/agents/{agent_id}/notebook-revisions", dependencies=spectator)
def get_notebook_revisions(
    run_id: str, agent_id: AgentId, store: Store, cursor: str | None = None, limit: Limit = None
) -> Page[NotebookRevision]:
    filters: dict[str, object] = {"agent": agent_id}
    as_of = _cursor_point(store, run_id, cursor, filters)
    as_of_tick = _tick_at_sequence(store, run_id, as_of)
    revisions = [r for r in store.notebook_revisions(run_id, agent_id) if r.tick <= as_of_tick]
    return _page(revisions, cursor, limit, filters, as_of)


@router.get("/runs/{run_id}/radio", dependencies=spectator)
def get_radio(
    run_id: str,
    store: Store,
    from_tick: int | None = None,
    to_tick: int | None = None,
    sender: AgentId | None = None,
    cursor: str | None = None,
    limit: Limit = None,
) -> Page[RadioRecord]:
    filters: dict[str, object] = {"from": from_tick, "to": to_tick, "sender": sender}
    as_of = _cursor_point(store, run_id, cursor, filters)
    records = [
        r
        for r in store.radio(run_id)
        if r.sequence <= as_of
        and (from_tick is None or r.sent_tick >= from_tick)
        and (to_tick is None or r.sent_tick <= to_tick)
        and (sender is None or r.sender == sender)
    ]
    return _page(records, cursor, limit, filters, as_of)


@router.get("/runs/{run_id}/timeline", dependencies=spectator)
def get_timeline(
    run_id: str,
    store: Store,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    to_tick: int | None = None,
    types: Annotated[list[str] | None, Query()] = None,
    agent: AgentId | None = None,
    cursor: str | None = None,
    limit: Limit = None,
) -> Page[EventEnvelope]:
    filters: dict[str, object] = {"after": after_sequence, "to": to_tick, "types": types, "agent": agent}
    as_of = _cursor_point(store, run_id, cursor, filters)
    size = page_limit(limit)
    offset, _ = decode_cursor(cursor, filters, as_of)
    # offset here is the last sequence already returned, so pages are stable under appends
    events = store.events(
        run_id,
        after_sequence=max(after_sequence, offset),
        to_tick=to_tick,
        types=types,
        agent_id=agent,
        limit=size + 1,
    )
    events = [e for e in events if e.sequence <= as_of]
    more = len(events) > size
    events = events[:size]
    next_cursor = encode_cursor(events[-1].sequence, filters, as_of) if more and events else None
    return Page[EventEnvelope](items=events, next_cursor=next_cursor, as_of_sequence=as_of)


@router.get("/runs/{run_id}/invocations", dependencies=spectator)
def get_invocations(
    run_id: str,
    store: Store,
    agent: AgentId | None = None,
    tick: int | None = None,
    cursor: str | None = None,
    limit: Limit = None,
) -> Page[InvocationRecord]:
    filters: dict[str, object] = {"agent": agent, "tick": tick}
    as_of = _cursor_point(store, run_id, cursor, filters)
    as_of_tick = _tick_at_sequence(store, run_id, as_of)
    records = [r for r in store.invocations(run_id, tick=tick, agent_id=agent) if r.tick <= as_of_tick]
    return _page(records, cursor, limit, filters, as_of)


def _tick_at_sequence(store: RunStore, run_id: str, sequence: int) -> int:
    events = store.events(run_id, after_sequence=sequence - 1, limit=1)
    return events[0].tick if events else read_point(store, run_id).state_tick


# ---- export -----------------------------------------------------------------


@router.get("/runs/{run_id}/export", dependencies=spectator, response_class=Response)
def get_export(run_id: str, store: Store) -> Response:
    read_point(store, run_id)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{run_id}.zip"
        export_run(store, run_id, path)
        data = path.read_bytes()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )
