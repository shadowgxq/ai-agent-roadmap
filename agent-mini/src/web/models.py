"""In-memory Web domain models for sessions, runs, and messages."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# 这些 Literal 集合同时约束内存状态和 API 输出，避免前后端自行扩展出不一致的状态值。
SessionStatus = Literal["active", "archived"]
MessageRole = Literal["user", "assistant", "tool"]
MessageKind = Literal["text", "tool_call", "tool_result", "diff"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting_confirmation",
    "completed",
    "failed",
    "max_turns",
    "cancelled",
]


def utc_now() -> datetime:
    """返回带时区的 UTC 时间，避免 Session 时间混用本地时区。"""
    return datetime.now(timezone.utc)


class Session(BaseModel):
    """一次连续对话的容器；它的状态不等同于某个 Run 的状态。"""

    session_id: str = Field(min_length=1)
    status: SessionStatus = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(BaseModel):
    """Session 中的一条用户、助手或工具消息。"""

    message_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    role: MessageRole
    kind: MessageKind = "text"
    content: str
    # 只保存展示/查询所需的轻量索引（例如 turn），不把消息记录当作模型 Context。
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Run(BaseModel):
    """一次由用户消息触发的完整 Agent Loop。"""

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    status: RunStatus = "queued"
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    confirmation_id: str | None = None
    confirmation_command: str | None = None
    confirmation_reason: str | None = None


class SessionDetail(BaseModel):
    """Session 详情及其关联的 Runs、Messages。"""

    # 详情接口按 Session 聚合两类历史，前端无需再次按 session_id 分组。
    session: Session
    runs: list[Run] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
