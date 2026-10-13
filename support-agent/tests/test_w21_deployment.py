"""Read-only deployment/HTTP checks; no Docker daemon, network sockets or providers."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
import pytest
import yaml

from support_agent.application.api import create_app
from support_agent.application.settings import ApplicationSettings
from support_agent.application.telemetry import Telemetry
from support_agent.evaluation.live import collect_live
from test_w20_api import client, login, RUN_ID


ROOT = Path(__file__).resolve().parents[2]


def test_compose_graph_migrates_before_workers_and_keeps_databases_internal():
    config = yaml.safe_load((ROOT / "compose.support.yaml").read_text())
    services = config["services"]
    assert {"frontend", "api", "worker", "scheduler", "migrate", "postgres", "redis"} <= services.keys()
    for name in ("postgres", "redis", "api"):
        assert "ports" not in services[name]
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["command"] == ["support-app", "migrate"]
    assert all("healthcheck" in services[name] for name in ("api", "worker", "scheduler", "postgres", "redis"))
    assert "proxy_buffering off" in (ROOT / "deploy/nginx.conf").read_text()
    assert "**/.env" in (ROOT / ".dockerignore").read_text()


def test_live_collection_refuses_to_contact_anything_without_explicit_cost_permission():
    with pytest.raises(PermissionError):
        asyncio.run(collect_live("http://unused", {}, [], [], permit_model_calls=False))


def test_finite_history_snapshot_and_readiness_have_no_model_dependency():
    c = client()
    login(c)
    rows = c.get(f"/support-api/runs/{RUN_ID}/event-history").json()
    assert [row["sequence"] for row in rows] == [1, 2]
    class Store:
        @asynccontextmanager
        async def connection(self):
            async def execute(sql):
                assert "support_runs" in sql
            yield SimpleNamespace(execute=execute)
    settings = ApplicationSettings(database_url="unused", session_secret="x" * 32, _env_file=None)
    c = TestClient(create_app(settings, Store()))
    assert c.get("/health/live").status_code == c.get("/health/ready").status_code == 200


def test_recovered_attempt_does_not_claim_unobserved_tokens_or_total_e2e_cost():
    trace = Telemetry({"run_id": "r", "thread_id": "t", "ticket_id": "ticket", "attempt": 2}, "fixture", input_price=1, output_price=1)
    assert trace.metrics()["cost_usd"] is None
    assert trace.metrics()["input_tokens"] is None
    assert trace.metrics()["cost_scope"] == "chat-generations-only"


def test_checkpoint_evidence_round_trip_uses_an_explicit_type_allowlist():
    from support_agent.models import EvidenceRef
    from support_agent.persistence.checkpointer import ticket_serializer
    serializer = ticket_serializer()
    evidence = EvidenceRef(source_id="chunk", title="Policy", snippet="Evidence")
    assert serializer.loads_typed(serializer.dumps_typed(evidence)) == evidence
