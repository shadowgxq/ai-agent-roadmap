"""Minimal FastAPI and SSE surface for the Agent execution viewer."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent.config import AgentSettings
from .runs import RunManager


class RunRequest(BaseModel):
    task: str = Field(min_length=1)


class RunCreated(BaseModel):
    run_id: str
    status: str


def create_app(
    *,
    workdir: Path | None = None,
    settings: AgentSettings | None = None,
) -> FastAPI:
    """Build an app with an explicit workdir and optional injected settings."""
    configured_workdir = workdir or Path(
        os.environ.get("AGENT_WORKDIR", Path.cwd())
    )
    manager = RunManager(workdir=configured_workdir, settings=settings)
    app = FastAPI(title="agent-mini viewer")
    app.state.run_manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.post("/runs", response_model=RunCreated, status_code=202)
    async def create_run(request: RunRequest) -> RunCreated:
        try:
            state = await manager.start(request.task)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RunCreated(run_id=state.run_id, status=state.status)

    @app.get("/runs/{run_id}/events")
    async def stream_events(run_id: str) -> StreamingResponse:
        try:
            manager.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            manager.stream(run_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
