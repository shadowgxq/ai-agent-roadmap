"""Stable event schema shared by the Agent backend and future frontends."""

from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal["text", "tool_call", "tool_result", "done"]


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
