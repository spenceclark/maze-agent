"""Event streaming over SSE and WebSocket (spec §11.3).

Both transports carry identical `EventEnvelope` JSON. A client resumes after a
sequence: the durable journal is replayed from there, then live events follow.
Subscribing happens before the journal read, and duplicates are dropped by
sequence, so nothing committed between the two can be missed.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from maze_lab.api.common import Service, read_point, require, websocket_allowed
from maze_lab.coordinator import TERMINAL
from maze_lab.persistence.models import EventEnvelope
from maze_lab.service import RunService

router = APIRouter(prefix="/api/v1")

HEARTBEAT_SECONDS = 15.0
Heartbeat = Literal["heartbeat"]
Resync = Literal["resync"]


async def event_stream(
    service: RunService, run_id: str, after_sequence: int, heartbeat: float = HEARTBEAT_SECONDS
) -> AsyncIterator[EventEnvelope | Heartbeat | Resync]:
    sub = service.hub.subscribe(run_id)
    try:
        last = after_sequence
        for event in service.store.events(run_id, after_sequence=after_sequence):
            yield event
            last = event.sequence
            if event.type == "run.completed":
                return
        summary = service.store.summary(run_id)
        if summary is not None and summary.status in TERMINAL:
            return  # everything is already durable and was replayed above
        while True:
            try:
                item = await asyncio.wait_for(service.hub.next(sub), heartbeat)
            except TimeoutError:
                yield "heartbeat"
                continue
            if item is None:
                yield "resync"  # this client fell too far behind; it must re-bootstrap
                return
            if item.sequence <= last:
                continue
            yield item
            last = item.sequence
            if item.type == "run.completed":
                return
    finally:
        service.hub.unsubscribe(sub)


def _sse(item: EventEnvelope | Heartbeat | Resync) -> str:
    if item == "heartbeat":
        return ": heartbeat\n\n"  # comment frame: consumes no sequence
    if item == "resync":
        return 'event: resync\ndata: {"reason":"client_lagging"}\n\n'
    return f"id: {item.sequence}\nevent: {item.type}\ndata: {item.model_dump_json()}\n\n"


@router.get("/runs/{run_id}/events", dependencies=[require("spectator")], response_class=StreamingResponse)
async def sse_events(
    run_id: str,
    request: Request,
    service: Service,
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    read_point(service.store, run_id)
    after = after_sequence if after_sequence is not None else int(last_event_id or 0)

    async def frames() -> AsyncIterator[str]:
        async for item in event_stream(service, run_id, after):
            if await request.is_disconnected():
                return
            yield _sse(item)

    return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.websocket("/runs/{run_id}/ws")
async def ws_events(websocket: WebSocket, run_id: str, after_sequence: int = 0) -> None:
    """Server sends envelopes; the client may send {"type":"ping"} or {"type":"resume","after_sequence":n}."""
    if not websocket_allowed(websocket):
        await websocket.close(code=1008)
        return
    service: RunService = websocket.app.state.service
    if service.store.summary(run_id) is None:
        await websocket.close(code=1008, reason="no such run")
        return
    await websocket.accept()

    async def pump(after: int) -> None:
        async for item in event_stream(service, run_id, after):
            if item == "heartbeat":
                continue  # WebSocket has its own keepalive
            if item == "resync":
                await websocket.send_json({"type": "resync", "reason": "client_lagging"})
                return
            await websocket.send_text(item.model_dump_json())

    sender = asyncio.create_task(pump(after_sequence))
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "resume":
                sender.cancel()
                sender = asyncio.create_task(pump(int(message.get("after_sequence", 0))))
    except WebSocketDisconnect, json.JSONDecodeError, ValueError:
        pass
    finally:
        sender.cancel()
