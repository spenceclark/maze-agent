"""FastAPI application factory.

One process owns the coordinators and the SQLite database; never run this
with multiple workers (spec §9.3). Without tokens the server is meant for
loopback only; set tokens for anything reachable remotely.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from maze_lab.api import routes, stream
from maze_lab.api.common import ApiError, error_response, from_service_error
from maze_lab.api.schemas import Health
from maze_lab.persistence.store import RunStore
from maze_lab.service import EventHub, RunService, ServiceError

VIEWER_DIST = Path(__file__).resolve().parents[3] / "ui" / "dist"


def create_app(
    db_path: str | Path,
    spectator_token: str | None = None,
    operator_token: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = RunStore(db_path)
        service = RunService(store, EventHub())
        app.state.service = service
        await service.startup()
        try:
            yield
        finally:
            await service.shutdown()
            store.close()

    app = FastAPI(title="maze-lab spectator API", version="1.0", lifespan=lifespan)
    app.state.tokens = {
        "spectator": spectator_token or os.environ.get("MAZE_LAB_SPECTATOR_TOKEN"),
        "operator": operator_token or os.environ.get("MAZE_LAB_OPERATOR_TOKEN"),
    }

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError) -> JSONResponse:
        return error_response(e.status, e.code, e.message, e.details)

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, e: ServiceError) -> JSONResponse:
        return from_service_error(e)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, e: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "invalid_request", "request failed validation", {"errors": jsonable_encoder(e.errors())}
        )

    @app.get("/health/live")
    def live() -> Health:
        return Health(status="ok")

    @app.get("/health/ready")
    def ready(request: Request) -> JSONResponse:
        service: RunService = request.app.state.service
        ok = service.ready and service.store.ping()
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "starting"})

    app.include_router(routes.router)
    app.include_router(stream.router)
    if VIEWER_DIST.is_dir():  # the built React viewer, if present (`npm run build` in ui/)
        app.mount("/", StaticFiles(directory=VIEWER_DIST, html=True), name="viewer")
    return app
