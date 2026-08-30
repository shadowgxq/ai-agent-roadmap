"""Business records for W15 approvals and idempotent tool actions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .workflow import ApprovalDecision


ToolActionStatus = Literal["pending", "succeeded", "failed", "unknown"]


class ApprovalRecord(BaseModel):
    """One durable human decision bound to an exact proposal."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: str
    ticket_id: str
    run_id: str
    thread_id: str
    actor_id: str
    decision: ApprovalDecision
    feedback: str | None
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decided_at: datetime


class ToolActionRecord(BaseModel):
    """Durable execution state for one idempotent external action."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: str
    ticket_id: str
    run_id: str
    action_type: str
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ToolActionStatus
    request_json: dict[str, object]
    result_json: dict[str, object] | None
    created_at: datetime
    completed_at: datetime | None
