"""Stable event schema shared by the Agent backend and future frontends."""

from typing import Any, Literal, TypeGuard

from pydantic import BaseModel, Field


EventType = Literal[
    "text",
    "tool_call",
    "tool_result",
    "context_usage",
    "done",
]

PUBLIC_EVENT_TYPES = frozenset(
    {
        "text",
        "tool_call",
        "tool_result",
        "context_usage",
        "done",
    }
)


def is_public_event(event: str) -> TypeGuard[EventType]:
    """判断事件是否允许穿过 Web Adapter 进入 SSE。"""
    return event in PUBLIC_EVENT_TYPES


class AgentEvent(BaseModel):
    """One ordered event in a single Agent run."""

    sequence: int = Field(ge=0)
    run_id: str = Field(min_length=1)
    event: EventType
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        """Serialize the event using the browser EventSource format."""
        return (
            f"id: {self.sequence}\n"
            f"event: {self.event}\n"
            f"data: {self.model_dump_json()}\n\n"
        )
