"""Minimal FastAPI and SSE surface for the Agent execution viewer."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent.config import AgentSettings
from .models import Session, SessionDetail
from .runs import AgentRunner, RunManager


# 两条创建 Run 的路由共享同一份输入约束，避免空任务进入异步执行层。
class RunRequest(BaseModel):
    task: str = Field(min_length=1)


# 创建响应同时返回 Session/Message 关联键，前端可以立即订阅 Run 并定位历史消息。
class RunCreated(BaseModel):
    run_id: str
    session_id: str
    message_id: str
    status: str


def create_app(
    *,
    workdir: Path | None = None,
    settings: AgentSettings | None = None,
    runner: AgentRunner | None = None,
) -> FastAPI:
    """Build an app with an explicit workdir and optional injected settings."""
    # 显式参数优先；未注入时才读取环境变量，便于测试或宿主按实例隔离工作目录。
    configured_workdir = workdir or Path(
        os.environ.get("AGENT_WORKDIR", Path.cwd())
    )
    manager = RunManager(
        workdir=configured_workdir,
        settings=settings,
        runner=runner,
    )
    app = FastAPI(title="agent-mini viewer")
    # 将 Manager 放入 app.state，既供路由闭包使用，也保留给宿主/调试工具查看运行态的入口。
    app.state.run_manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Session 路由负责生命周期和历史聚合；具体 Run 执行仍由同一个 Manager 统一协调。
    @app.post("/sessions", response_model=Session, status_code=201)
    async def create_session() -> Session:
        return manager.create_session()

    @app.get("/sessions", response_model=list[Session])
    async def list_sessions() -> list[Session]:
        return manager.list_sessions()

    @app.get("/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: str) -> SessionDetail:
        try:
            return manager.get_session_detail(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/sessions/{session_id}/runs",
        response_model=RunCreated,
        status_code=202,
    )
    async def create_session_run(
        session_id: str,
        request: RunRequest,
    ) -> RunCreated:
        try:
            state = await manager.start(request.task, session_id=session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RunCreated(
            run_id=state.run_id,
            session_id=state.session_id,
            message_id=state.message_id,
            status=state.status,
        )

    # 保留无 Session 的旧入口；它会由 Manager 自动创建 Session，兼容已有调用方。
    @app.post("/runs", response_model=RunCreated, status_code=202)
    async def create_run(request: RunRequest) -> RunCreated:
        try:
            state = await manager.start(request.task)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RunCreated(
            run_id=state.run_id,
            session_id=state.session_id,
            message_id=state.message_id,
            status=state.status,
        )

    @app.get("/runs/{run_id}/events")
    async def stream_events(run_id: str) -> StreamingResponse:
        # 先同步确认 Run 存在，再创建 StreamingResponse，避免把 404 延迟到流连接之后。
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
