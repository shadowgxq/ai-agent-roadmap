"""New fault regressions; W20 concurrency/security cases are reused directly."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from psycopg import OperationalError
import pytest

from support_agent.application.queue import dispatch_pending, redacted_task
from support_agent.application.store import ApplicationStore
from support_agent.application.worker import execute_run
from support_agent.evaluation.catalog import load_catalog
from support_agent.evaluation.offline import execute_offline
from support_agent.evaluation.report import assess
from test_w20_recovery import MemoryControlStore, SETTINGS


def test_publish_interruption_leaves_outbox_for_redelivery():
    async def scenario():
        committed = []
        published = []
        class Connection:
            staged = []
            async def execute(self, sql, params=None):
                if "UPDATE support_outbox" in sql:
                    self.staged.append(params[1])
                async def fetchall():
                    return [{"organization_id": "a", "run_id": "one", "generation": 1},
                            {"organization_id": "a", "run_id": "two", "generation": 1}]
                return SimpleNamespace(fetchall=fetchall)
        @asynccontextmanager
        async def connection():
            conn = Connection()
            try:
                yield conn
            except Exception:
                conn.staged.clear()
                raise
            else:
                committed.extend(conn.staged)
        def publish(org, run_id, generation):
            if run_id == "two":
                raise ConnectionError("Simulated Redis outage")
            published.append(run_id)
        with pytest.raises(ConnectionError):
            await dispatch_pending(SimpleNamespace(connection=connection), publish)
        assert published == ["one"] and committed == []
    asyncio.run(scenario())


def test_db_read_failure_requeues_without_entering_an_engine():
    async def scenario():
        store = MemoryControlStore()
        async def outage(*args):
            raise OperationalError("private database connection details")
        store.ticket = outage
        async def forbidden(*args):
            pytest.fail("DB failure must precede engine/provider calls")
        await execute_run(store, SETTINGS, "org-a", "0", 1, forbidden)
        assert store.runs["0"]["status"] == "queued" and store.runs["0"]["generation"] == 2
    asyncio.run(scenario())


def test_stale_worker_cannot_save_terminal_events(monkeypatch):
    async def scenario():
        store = ApplicationStore("unused")
        @asynccontextmanager
        async def connection():
            yield object()
        async def lock(*args):
            return {"status": "running", "lease_token": "new-token"}
        monkeypatch.setattr(store, "connection", connection)
        monkeypatch.setattr(store, "lock_run", lock)
        assert not await store.finish({"organization_id": "a", "run_id": "r", "lease_token": "old-token"}, "succeeded", {})
    asyncio.run(scenario())


def test_disconnect_is_not_a_persistent_terminal_event():
    manifest, cases, corpus = load_catalog()
    case = next(case for case in cases if case.id == "low-export")
    row = asyncio.run(execute_offline(case, manifest, corpus, "disconnect"))
    row["events"][-1]["kind"] = "stream_closed"
    assert "infra" in assess(case, row)["failure_categories"]


def test_celery_error_text_does_not_export_provider_or_database_credentials():
    @redacted_task
    def fails():
        raise ConnectionError("api_key=sk-private customer@example.com")
    with pytest.raises(RuntimeError) as error:
        fails()
    assert str(error.value) == "ConnectionError" and error.value.__suppress_context__
