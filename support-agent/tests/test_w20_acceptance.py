"""Fixed adversarial host-gate regressions, not a real-model injection success metric."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from support_agent.application.contracts import Identity
from support_agent.application.security import redact, validate_crm_request
from support_agent.application.store import ApplicationStore, CancelledRun
from support_agent.knowledge.citations import validate_citations
from test_w20_security import authorized_request


CASES = json.loads((Path(__file__).resolve().parents[1] / "evals/w20_security_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_adversarial_host_gates_prevent_unapproved_writes(case, monkeypatch):
    run, request = authorized_request()
    attack = case["attack"]
    changes = {"tenant": {"organization_id": "b"}, "ticket": {"ticket_id": "b"},
               "run": {"run_id": "b"}, "delete": {"status": "deleted"},
               "extra_parameter": {"authorization": "admin"}, "fake_key": {"idempotency_key": "fake"},
               "shell": {"tool": "shell"}}
    if attack in changes:
        with pytest.raises(PermissionError):
            validate_crm_request(run, request | changes[attack])
    elif attack in {"viewer", "operator_approval"}:
        with pytest.raises(PermissionError):
            Identity("a", "u", "viewer" if attack == "viewer" else "operator").require("operator" if attack == "viewer" else "approver")
    elif attack == "citation":
        assert not validate_citations("Approved [forged-source]", {"actual-source"}).valid
    elif attack == "redaction":
        assert redact({"api_key": "private", "reply": "client@example.com"}) == {"api_key": "[redacted]", "reply": "[email]"}
    else:
        async def scenario():
            store = ApplicationStore("unused")
            leased = run | {"status": "running", "lease_token": "token", "projection": {"proposal_hash": "hash"}, "cancel_requested": attack == "cancelled"}
            current = leased | {"lease_token": "other" if attack == "stale" else "token"}
            class Conn:
                async def execute(self, query, params=None):
                    async def fetchone():
                        return {"valid": True} if "lease_until>now()" in query else {"decision": "reject"} if attack == "rejected" else None
                    return SimpleNamespace(fetchone=fetchone)
            @asynccontextmanager
            async def connection():
                yield Conn()
            async def lock_run(*args):
                return current
            monkeypatch.setattr(store, "connection", connection)
            monkeypatch.setattr(store, "lock_run", lock_run)
            side_effects = 0
            with pytest.raises((PermissionError, CancelledRun)):
                async with store.tool_guard(leased, request):
                    side_effects += 1
            assert side_effects == 0
        asyncio.run(scenario())
