"""Typed ticket models used by the support agent."""

from typing import Literal

from pydantic import BaseModel, Field


TicketCategory = Literal["refund", "billing", "technical", "account", "other"]
TicketPriority = Literal["low", "medium", "high", "urgent"]


class TicketClassification(BaseModel):
    """Validated classification returned by the agent."""

    category: TicketCategory = Field(description="工单所属业务类别")
    priority: TicketPriority = Field(description="工单处理优先级")
    needs_clarification: bool = Field(description="是否需要用户补充信息")
    reason: str = Field(min_length=1, description="分类和优先级判断依据")
