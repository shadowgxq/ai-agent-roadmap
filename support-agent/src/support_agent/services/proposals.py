"""Canonical identities for approval proposals and tool actions."""

import hashlib
import json
from collections.abc import Mapping


def canonical_json(data: Mapping[str, object]) -> str:
    """Serialize JSON data deterministically before hashing it."""

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(data: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def build_proposal_hash(
    *,
    draft_response: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    """Bind human approval to the exact draft, tool, and arguments."""

    return _sha256({
        "draft_response": draft_response,
        "tool_name": tool_name,
        "arguments": dict(arguments),
    })


def build_idempotency_key(
    *,
    organization_id: str,
    ticket_id: str,
    run_id: str,
    action_type: str,
    payload: Mapping[str, object],
) -> str:
    """Build the stable identity of one intended external side effect."""

    return _sha256({
        "organization_id": organization_id,
        "ticket_id": ticket_id,
        "run_id": run_id,
        "action_type": action_type,
        "payload": dict(payload),
    })
