"""Local control-flow tests; these do not claim PostgreSQL/Redis integration proof."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from support_agent.application.contracts import check_transition
from support_agent.application.store import ApplicationStore, CancelledRun
from support_agent.application.worker import execute_run


class MemoryControlStore:
    def __init__(self, count=1):
        self.lock = asyncio.Lock()
        self.runs = {str(index): {"organization_id": "org-a", "user_id": "u", "run_id": str(index),
             "ticket_id": str(index), "status": "queued", "generation": 1, "attempt": 0,
             "lease_token": None, "cancel_requested": False, "sequence": 1} for index in range(count)}
        self.events = {key: [(1, "queued")] for key in self.runs}

    def change(self, run, status):
        check_transition(run["status"], status)
        run["status"] = status
        run["sequence"] += 1
        self.events[run["run_id"]].append((run["sequence"], status))

    async def claim(self, org, run_id, generation, lease_seconds):
        async with self.lock:
            run = self.runs[run_id]
            if run["organization_id"] != org or run["status"] != "queued" or run["generation"] != generation:
                return None
            run["lease_token"] = uuid4()
            run["attempt"] += 1
            self.change(run, "running")
            return dict(run)

    async def ticket(self, actor, ticket_id):
        return {"ticket_id": ticket_id}

    async def heartbeat(self, run, lease_seconds):
        current = self.runs[run["run_id"]]
        return current["lease_token"] == run["lease_token"] and not current["cancel_requested"]

    async def finish(self, run, status, projection):
        async with self.lock:
            current = self.runs[run["run_id"]]
            if current["status"] != "running" or current["lease_token"] != run["lease_token"]:
                return False
            self.change(current, "cancelled" if current["cancel_requested"] else status)
            return True

    async def retry(self, run, error_code, max_attempts):
        current = self.runs[run["run_id"]]
        self.change(current, "failed" if current["attempt"] >= max_attempts else "queued")
        current["generation"] += 1
        current["lease_token"] = None


SETTINGS = SimpleNamespace(lease_seconds=30, max_attempts=2)


def test_twenty_concurrent_runs_ignore_duplicate_delivery():
    async def scenario():
        store = MemoryControlStore(20)
        async def engine(*args):
            await asyncio.sleep(0)
            return "succeeded", {}
        await asyncio.gather(*(execute_run(store, SETTINGS, "org-a", str(index), 1, engine)
                               for index in range(20) for duplicate in range(2)))
        assert all(run["status"] == "succeeded" and run["attempt"] == 1 for run in store.runs.values())
        for events in store.events.values():
            assert len({sequence for sequence, _ in events}) == len(events)
            assert sum(status == "succeeded" for _, status in events) == 1
    asyncio.run(scenario())


def test_timeout_retry_is_bounded_and_old_generation_cannot_restart():
    async def scenario():
        store = MemoryControlStore()
        async def timeout(*args):
            raise TimeoutError("secret provider body")
        await execute_run(store, SETTINGS, "org-a", "0", 1, timeout)
        assert store.runs["0"]["status"] == "queued"
        await execute_run(store, SETTINGS, "org-a", "0", 1, timeout)
        assert store.runs["0"]["attempt"] == 1
        await execute_run(store, SETTINGS, "org-a", "0", 2, timeout)
        assert store.runs["0"]["status"] == "failed" and store.runs["0"]["attempt"] == 2
    asyncio.run(scenario())


def test_cooperative_cancel_finishes_without_retry():
    async def scenario():
        store = MemoryControlStore()
        async def cancelled(*args):
            store.runs["0"]["cancel_requested"] = True
            raise CancelledRun()
        await execute_run(store, SETTINGS, "org-a", "0", 1, cancelled)
        assert store.runs["0"]["status"] == "cancelled"
    asyncio.run(scenario())


def test_unknown_write_outcome_does_not_create_retry_outbox(monkeypatch):
    async def scenario():
        store = ApplicationStore("unused")
        statements = []
        transitions = []
        class Conn:
            async def execute(self, sql, params=None):
                statements.append(sql)
                async def fetchone():
                    return {"exists": True}
                return SimpleNamespace(fetchone=fetchone)
        async def change(conn, run, status, payload):
            transitions.append((status, payload))
        monkeypatch.setattr(store, "change", change)
        await store.requeue_or_fail(Conn(), {"organization_id": "a", "run_id": "r", "attempt": 1, "cancel_requested": False}, "timeout", 3)
        assert transitions == [("failed", {"error_code": "TOOL_OUTCOME_UNKNOWN"})]
        assert not any("INSERT INTO support_outbox" in sql for sql in statements)
    asyncio.run(scenario())


def test_cross_tenant_worker_message_is_rejected():
    async def scenario():
        store = MemoryControlStore()
        async def forbidden(*args):
            pytest.fail("Wrong tenant must not invoke an engine")
        await execute_run(store, SETTINGS, "org-b", "0", 1, forbidden)
        assert store.runs["0"]["status"] == "queued"
    asyncio.run(scenario())
