"""Typed records returned by the local W15 mock CRM."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CrmTicketRecord(BaseModel):
    """Current durable state of one ticket in the local mock CRM."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str
    ticket_id: str
    status: str
    update_count: int = Field(ge=1)
    last_idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    updated_at: datetime


class CrmUpdateResult(BaseModel):
    """Stable tool result plus whether it came from an earlier execution."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str
    ticket_id: str
    status: str
    update_count: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool
