import pytest
from support_agent.application.auth import Sessions, password_hash
from support_agent.application.contracts import Identity, check_transition, ConflictError, TicketInput
from support_agent.application.settings import ApplicationSettings


def sessions():
    return Sessions(ApplicationSettings(database_url="unused", session_secret="x" * 32,
        accounts={"operator": {"password_hash": password_hash("test-password"),
                  "organization_id": "org-a", "user_id": "user-a", "role": "operator"}}, _env_file=None))


def test_session_identity_is_signed_and_not_client_selected():
    auth = sessions()
    token = auth.login("operator", "test-password")
    assert auth.identity(token) == Identity("org-a", "user-a", "operator")
    with pytest.raises(PermissionError):
        auth.identity(token[:-1] + ("a" if token[-1] != "a" else "b"))
    with pytest.raises(PermissionError):
        auth.login("operator", "wrong-password")


def test_payload_cannot_override_tenant():
    with pytest.raises(ValueError):
        TicketInput(subject="test", description="test", knowledge_base_id="kb", organization_id="other")


def test_terminal_run_cannot_be_restarted():
    for status in ("succeeded", "failed", "cancelled"):
        with pytest.raises(ConflictError):
            check_transition(status, "queued")
    check_transition("waiting_approval", "queued")


def test_role_does_not_authorize_itself():
    with pytest.raises(PermissionError):
        Identity("a", "b", "viewer").require("operator")
