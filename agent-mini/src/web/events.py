"""Public Agent Event Protocol shared by the backend and frontend."""

from typing import Any, Literal, Self, TypeGuard

from pydantic import BaseModel, Field, model_validator


# EventType 是 Runtime 与 Web/SSE 之间的公开边界；内部观测事件不能直接暴露给浏览器。
EventType = Literal[
    "text",
    "tool_call",
    "tool_result",
    "context_usage",
    "done",
]
TerminalStatus = Literal[
    "completed",
    "failed",
    "max_turns",
    "cancelled",
]

# 公开事件集合用于运行时过滤，Literal 则负责让序列化后的 envelope 保持可预测。
PUBLIC_EVENT_TYPES = frozenset(
    {
        "text",
        "tool_call",
        "tool_result",
        "context_usage",
        "done",
    }
)
# Runtime 可能产生 compact_usage，但它属于内部观测数据，不进入 v1 公共协议。
INTERNAL_EVENT_TYPES = frozenset({"compact_usage"})


# 文本事件的 turn 用于前端按 Agent 轮次归组；空文本不应占用一个公开事件序号。
class TextEventData(BaseModel):
    turn: int = Field(ge=1)
    text: str = Field(min_length=1)


# tool_call 与 tool_result 通过同一个 tool_use_id 配对；arguments 保留 Runtime 的原始 JSON 字符串。
class ToolCallItem(BaseModel):
    tool_use_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str


# 一次事件可以批量携带同一轮的多个工具调用，但每个调用仍需独立的 tool_use_id。
class ToolCallEventData(BaseModel):
    turn: int = Field(ge=1)
    calls: list[ToolCallItem] = Field(min_length=1)


# 工具结果保留公开展示所需的错误标记，配对完整性由 RunManager 在事件流层继续校验。
class ToolResultItem(BaseModel):
    tool_use_id: str = Field(min_length=1)
    content: str
    is_error: bool


class ToolResultEventData(BaseModel):
    turn: int = Field(ge=1)
    results: list[ToolResultItem] = Field(min_length=1)


# Provider 不提供 token 用量时使用 None + available=false，不能把“未知”误报成 0。
class ContextUsageEventData(BaseModel):
    turn: int = Field(ge=1)
    context_tokens: int | None = Field(default=None, ge=0)
    context_window_tokens: int = Field(gt=0)
    context_usage_percent: float | None = Field(default=None, ge=0)
    available: bool


# done 是唯一终态；达到 max_turns 时必须带上上限，方便前端解释 Run 为何结束。
class DoneEventData(BaseModel):
    status: TerminalStatus
    turn: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    error: str | None = None
    max_turns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_max_turns_for_limit_status(self) -> Self:
        if self.status == "max_turns" and self.max_turns is None:
            raise ValueError("max_turns 终态必须携带 max_turns")
        return self


# 事件 envelope 只负责选择 payload 校验器，具体字段约束由各事件模型维护。
EVENT_DATA_MODELS: dict[EventType, type[BaseModel]] = {
    "text": TextEventData,
    "tool_call": ToolCallEventData,
    "tool_result": ToolResultEventData,
    "context_usage": ContextUsageEventData,
    "done": DoneEventData,
}


def is_public_event(event: str) -> TypeGuard[EventType]:
    """判断事件是否属于公开协议。"""
    return event in PUBLIC_EVENT_TYPES


def to_public_event(event: str) -> EventType | None:
    """适配 Runtime 事件；内部事件忽略，未知事件明确报错。"""
    if is_public_event(event):
        return event
    if event in INTERNAL_EVENT_TYPES:
        return None
    raise ValueError(f"未知 Agent Event，禁止进入 SSE: {event}")


class AgentEvent(BaseModel):
    """一个 Run 内按 sequence 排序的公共事件。"""

    sequence: int = Field(ge=0)
    run_id: str = Field(min_length=1)
    event: EventType
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_event_data(self) -> Self:
        # 先按事件类型校验，再 dump 回普通字典，保证嵌套 Pydantic 模型也按统一形状出现在 SSE 中。
        payload = EVENT_DATA_MODELS[self.event].model_validate(self.data)
        self.data = payload.model_dump()
        return self

    def to_sse(self) -> str:
        """使用浏览器 EventSource 格式序列化事件。"""
        return (
            f"id: {self.sequence}\n"
            f"event: {self.event}\n"
            f"data: {self.model_dump_json()}\n\n"
        )
