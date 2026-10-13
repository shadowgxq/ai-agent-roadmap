"""REST + resumable persisted SSE. The API only records work, never runs Graphs."""

import asyncio
import hmac
import json
from uuid import UUID

from fastapi import FastAPI, Depends, Request, Response, Header
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ConfigDict

from .auth import Sessions
from .contracts import ApprovalInput, ConflictError, Identity, NotFoundError, TicketInput, TERMINAL
from .settings import ApplicationSettings
from .store import ApplicationStore
from .security import redact, public_projection


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=1024)


def public_run(run: dict) -> dict:
    result = {key: run[key] for key in ("run_id", "ticket_id", "thread_id", "status", "sequence", "projection", "cancel_requested", "created_at") if key in run}
    if "projection" in result:
        result["projection"] = public_projection(result["projection"])
    return result


def sse_frame(row: dict) -> str:
    return f"id: {row['sequence']}\nevent: {row['kind']}\ndata: {json.dumps(jsonable_encoder(redact(row['payload'])), ensure_ascii=False)}\n\n"


def create_app(settings: ApplicationSettings | None = None, store=None) -> FastAPI:
    settings = settings or ApplicationSettings()
    store = store or ApplicationStore(settings.database_url)
    sessions = Sessions(settings)
    app = FastAPI(title="Support Agent", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_credentials=True, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "Last-Event-ID"])

    async def identity(request: Request) -> Identity:
        token = request.cookies.get("support_session", "")
        actor = sessions.identity(token)
        if request.method != "GET":
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), sessions.csrf(token)):
                raise PermissionError("Invalid CSRF token")
        return actor

    async def errors(request, exc):
        code = 404 if isinstance(exc, NotFoundError) else 409 if isinstance(exc, ConflictError) else 403 if isinstance(exc, PermissionError) else 400
        return JSONResponse(status_code=code, content={"detail": str(exc)})
    for exception in (NotFoundError, ConflictError, PermissionError, ValueError):
        app.add_exception_handler(exception, errors)

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Application temporarily unavailable"})

    @app.post("/support-api/auth/login")
    async def login(data: LoginInput, response: Response):
        token = sessions.login(data.username, data.password)
        response.set_cookie("support_session", token, httponly=True, secure=settings.secure_cookie,
                            samesite="strict", max_age=settings.session_seconds, path="/support-api")
        return {"identity": sessions.identity(token).__dict__, "csrf_token": sessions.csrf(token)}

    @app.get("/support-api/auth/session")
    async def session(request: Request, actor: Identity = Depends(identity)):
        return {"identity": actor.__dict__, "csrf_token": sessions.csrf(request.cookies["support_session"])}

    @app.post("/support-api/auth/logout")
    async def logout(response: Response, actor: Identity = Depends(identity)):
        response.delete_cookie("support_session", path="/support-api")
        return {"logged_out": True}

    @app.get("/support-api/tickets")
    async def tickets(actor: Identity = Depends(identity)):
        return redact(await store.tickets(actor))

    @app.post("/support-api/tickets", status_code=201)
    async def create_ticket(data: TicketInput, actor: Identity = Depends(identity)):
        actor.require("operator")
        return redact(await store.create_ticket(actor, data))

    @app.get("/support-api/tickets/{ticket_id}")
    async def ticket(ticket_id: UUID, actor: Identity = Depends(identity)):
        return redact(await store.ticket(actor, str(ticket_id)))

    @app.get("/support-api/tickets/{ticket_id}/runs")
    async def runs(ticket_id: UUID, actor: Identity = Depends(identity)):
        return [public_run(run) for run in await store.runs(actor, str(ticket_id))]

    @app.post("/support-api/tickets/{ticket_id}/runs", status_code=202)
    async def start(ticket_id: UUID, actor: Identity = Depends(identity), key: str = Header(alias="Idempotency-Key")):
        actor.require("operator")
        return public_run(await store.create_run(actor, str(ticket_id), key))

    @app.get("/support-api/runs/{run_id}")
    async def run(run_id: UUID, actor: Identity = Depends(identity)):
        return public_run(await store.run(actor, str(run_id)))

    @app.post("/support-api/runs/{run_id}/cancel")
    async def cancel(run_id: UUID, actor: Identity = Depends(identity)):
        actor.require("operator")
        return public_run(await store.cancel(actor, str(run_id)))

    @app.post("/support-api/runs/{run_id}/approval", status_code=202)
    async def approval(run_id: UUID, data: ApprovalInput, actor: Identity = Depends(identity)):
        actor.require("approver")
        return public_run(await store.approve(actor, str(run_id), data))

    @app.get("/support-api/runs/{run_id}/audit")
    async def audit(run_id: UUID, actor: Identity = Depends(identity)):
        return redact(await store.audit(actor, str(run_id)))

    @app.get("/support-api/runs/{run_id}/event-history")
    async def event_history(run_id: UUID, after: int = 0, actor: Identity = Depends(identity)):
        if after < 0:
            raise ValueError("Event cursor cannot be negative")
        # A finite snapshot for replay/export, including waiting-approval runs.
        return redact(await store.events(actor, str(run_id), after))

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready():
        async with store.connection() as conn:
            await conn.execute("SELECT 1 FROM support_runs LIMIT 1")
        return {"status": "ready"}

    @app.get("/support-api/runs/{run_id}/events")
    async def events(run_id: UUID, request: Request, after: int = 0,
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                     actor: Identity = Depends(identity)):
        cursor = int(last_event_id) if last_event_id is not None else after
        if cursor < 0:
            raise ValueError("Event cursor cannot be negative")
        await store.run(actor, str(run_id))
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                # A session that expires while streaming must reconnect and authenticate.
                sessions.identity(request.cookies.get("support_session", ""))
                rows = await store.events(actor, str(run_id), cursor)
                for row in rows:
                    cursor = row["sequence"]
                    yield sse_frame(row)
                    if row["kind"] == "done":
                        return
                current = await store.run(actor, str(run_id))
                if current["status"] in TERMINAL and current["sequence"] <= cursor:
                    return
                if not rows:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return app
