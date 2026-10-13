import pytest
from support_agent.application.security import public_projection, redact, validate_crm_request
from support_agent.services.proposals import build_idempotency_key


def authorized_request():
    run = {"organization_id": "org-a", "ticket_id": "ticket-a", "run_id": "run-a"}
    key = build_idempotency_key(**run, action_type="update_crm_ticket", payload={"ticket_id": "ticket-a", "status": "resolved"})
    return run, run | {"status": "resolved", "idempotency_key": key}


@pytest.mark.parametrize("change", [{"organization_id": "org-b"}, {"run_id": "other"}, {"ticket_id": "other"},
                                    {"status": "delete"}, {"idempotency_key": "fake"}, {"tool": "shell"}])
def test_model_text_cannot_grant_tool_permission(change):
    run, request = authorized_request()
    with pytest.raises(PermissionError):
        validate_crm_request(run, request | change)


def test_trace_and_public_projection_exclude_internal_reasoning():
    projection = public_projection({"thought": "private", "normalized_text": "secret", "draft_response": "email me@example.com; token=sk-private"})
    assert "thought" not in projection and "normalized_text" not in projection
    assert "me@example.com" not in projection["draft_response"] and "sk-private" not in projection["draft_response"]
    assert redact({"cookie": "secret", "password": "private"}) == {"cookie": "[redacted]", "password": "[redacted]"}


def test_valid_tool_parameters_are_accepted():
    run, request = authorized_request()
    validate_crm_request(run, request)
