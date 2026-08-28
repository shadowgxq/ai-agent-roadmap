"""Stable application events exposed by the W14 graph adapter."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AgentEventName = Literal[
    "status",
    "retrieval",
    "text",
    "tool_call",
    "tool_result",
    "context_usage",
    "diff",
    "approval_required",
    "done",
]


class AgentEvent(BaseModel):
    """Serializable envelope shared by CLI, SSE, and future UI adapters."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event: AgentEventName
    occurred_at: datetime
    data: dict[str, object] = Field(default_factory=dict)
