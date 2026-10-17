"""Shared API plumbing: error envelope, roles, consistent read points, cursors (spec §11)."""

import base64
import binascii
import hmac
import json
from typing import Annotated, Literal

from fastapi import Depends, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from maze_lab.hashing import content_hash
from maze_lab.persistence.store import RunStore
from maze_lab.service import RunService, ServiceError

DEFAULT_PAGE, MAX_PAGE = 100, 1000

Role = Literal["spectator", "operator"]


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def error_response(
    status: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}}
    )


def from_service_error(e: ServiceError) -> JSONResponse:
    return error_response(e.status, e.code, e.message)


# ---- dependencies -----------------------------------------------------------


def get_service(request: Request) -> RunService:
    return request.app.state.service


def get_store(request: Request) -> RunStore:
    return request.app.state.service.store


Service = Annotated[RunService, Depends(get_service)]
Store = Annotated[RunStore, Depends(get_store)]


def _granted(tokens: dict[Role, str | None], presented: str | None, role: Role) -> bool:
    """No tokens configured means local loopback development: everything is open."""
    if not any(tokens.values()):
        return True
    accepted = [t for r, t in tokens.items() if t and (r == role or r == "operator")]
    return presented is not None and any(hmac.compare_digest(presented, t) for t in accepted)


def require(role: Role):
    def check(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip() or None
        if not _granted(request.app.state.tokens, token, role):
            raise ApiError(401 if token is None else 403, "unauthorized", f"{role} access required")

    return Depends(check)


def websocket_allowed(websocket: WebSocket) -> bool:
    header = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    token = header or websocket.query_params.get("token")
    return _granted(websocket.app.state.tokens, token, "spectator")


# ---- consistent reads -------------------------------------------------------


class ReadPoint(BaseModel):
    """The committed tick and journal position a read is answered at."""

    run_id: str
    state_tick: int
    as_of_sequence: int


def read_point(store: RunStore, run_id: str, at_tick: int | None = None) -> ReadPoint:
    position = store.read_position(run_id)
    if position is None:
        raise ApiError(404, "not_found", f"no run {run_id}")
    latest_tick, latest_sequence = position
    if at_tick is None:
        return ReadPoint(run_id=run_id, state_tick=latest_tick, as_of_sequence=latest_sequence)
    if not 0 <= at_tick <= latest_tick:
        raise ApiError(409, "tick_not_committed", f"tick {at_tick} is not committed (latest {latest_tick})")
    commit = store.tick_commit(run_id, at_tick)
    assert commit is not None
    return ReadPoint(run_id=run_id, state_tick=at_tick, as_of_sequence=commit.last_sequence)


# ---- opaque cursors ---------------------------------------------------------


def encode_cursor(offset: int, filters: dict[str, object], as_of: int) -> str:
    raw = json.dumps({"o": offset, "f": content_hash(filters), "s": as_of}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, filters: dict[str, object], as_of: int) -> tuple[int, int]:
    """(offset, as_of_sequence). A cursor is bound to its filters and read point."""
    if cursor is None:
        return 0, as_of
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        offset, filter_hash, cursor_as_of = int(data["o"]), str(data["f"]), int(data["s"])
    except (binascii.Error, ValueError, KeyError, TypeError) as e:
        raise ApiError(400, "invalid_cursor", "cursor is malformed") from e
    if filter_hash != content_hash(filters):
        raise ApiError(400, "invalid_cursor", "cursor was issued for different filters")
    return offset, cursor_as_of


def page_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE
    if not 1 <= limit <= MAX_PAGE:
        raise ApiError(422, "invalid_limit", f"limit must be between 1 and {MAX_PAGE}")
    return limit
