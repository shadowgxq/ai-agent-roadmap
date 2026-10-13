"""ASGI in-process checks; no sockets, brokers, databases or models."""

from uuid import uuid4
from fastapi.testclient import TestClient
from support_agent.application.api import create_app
from support_agent.application.auth import password_hash
from support_agent.application.settings import ApplicationSettings


RUN_ID = str(uuid4())
TICKET_ID = str(uuid4())


class StoreDouble:
    async def tickets(self, actor):
        return [{"organization_id": actor.organization_id}]
    async def run(self, actor, run_id):
        return {"run_id": run_id, "status": "succeeded", "sequence": 2}
    async def events(self, actor, run_id, after):
        return [row for row in [{"sequence": 1, "kind": "status", "payload": {"status": "running"}},
                                {"sequence": 2, "kind": "done", "payload": {"status": "succeeded"}}] if row["sequence"] > after]
    async def create_ticket(self, actor, data):
        return {"ticket_id": TICKET_ID, "organization_id": actor.organization_id}


def client(role="operator"):
    settings = ApplicationSettings(database_url="unused", session_secret="x" * 32, secure_cookie=False,
        accounts={"user": {"password_hash": password_hash("test-password"), "user_id": "u",
                           "organization_id": "org-a", "role": role}}, _env_file=None)
    return TestClient(create_app(settings, StoreDouble()))


def login(c):
    result = c.post("/support-api/auth/login", json={"username": "user", "password": "test-password"})
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def test_server_session_and_csrf_boundary():
    c = client()
    assert c.get("/support-api/tickets").status_code == 403
    headers = login(c)
    assert c.get("/support-api/tickets").json()[0]["organization_id"] == "org-a"
    payload = {"subject": "help", "description": "help", "knowledge_base_id": "kb"}
    assert c.post("/support-api/tickets", json=payload).status_code == 403
    assert c.post("/support-api/tickets", headers=headers, json=payload).status_code == 201
    assert c.post("/support-api/tickets", headers=headers, json=payload | {"organization_id": "other"}).status_code == 422


def test_viewer_cannot_create_ticket():
    c = client("viewer")
    headers = login(c)
    assert c.post("/support-api/tickets", headers=headers, json={"subject": "help", "description": "help", "knowledge_base_id": "kb"}).status_code == 403


def test_sse_last_event_id_only_replays_remaining_events():
    c = client()
    login(c)
    response = c.get(f"/support-api/runs/{RUN_ID}/events", headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    assert "id: 2" in response.text and "id: 1" not in response.text
    assert "event: done" in response.text
