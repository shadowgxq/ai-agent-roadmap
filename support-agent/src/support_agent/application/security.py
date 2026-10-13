"""Host tool policy and a whitelist of public fields; model text grants no authority."""

import re
from support_agent.services.proposals import build_idempotency_key


PUBLIC_FIELDS = frozenset({"draft_response", "evidence_refs", "risk_level", "risk_reasons", "requires_approval",
                          "proposal_hash", "approval_decision", "revision_count", "tool_result", "tool_replayed", "error_code",
                          "trace_id", "metrics", "graph_status", "category", "missing_fields"})
SECRET_KEYS = frozenset({"api_key", "authorization", "cookie", "password", "access_token", "token"})


def redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if key.lower() in SECRET_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", value)
        value = re.sub(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)", "[phone]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[secret]", value)
        return re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|password|cookie|token)\s*[:=]\s*)[^\s,;]+", r"\1[secret]", value)
    if hasattr(value, "model_dump"):
        return redact(value.model_dump())
    return value


def public_projection(values: dict) -> dict:
    return redact({key: value for key, value in values.items() if key in PUBLIC_FIELDS})


def validate_crm_request(run: dict, request: dict) -> None:
    if set(request) != {"organization_id", "ticket_id", "run_id", "status", "idempotency_key"}:
        raise PermissionError("Tool parameters are not whitelisted")
    for key in ("organization_id", "ticket_id", "run_id"):
        if str(request[key]) != str(run[key]):
            raise PermissionError("Tool identity does not match the leased run")
    if request["status"] != "resolved":
        raise PermissionError("CRM status is not allowed")
    expected = build_idempotency_key(organization_id=request["organization_id"], ticket_id=request["ticket_id"],
        run_id=request["run_id"], action_type="update_crm_ticket", payload={"ticket_id": request["ticket_id"], "status": "resolved"})
    if request["idempotency_key"] != expected:
        raise PermissionError("Tool idempotency key does not match the approved action")
