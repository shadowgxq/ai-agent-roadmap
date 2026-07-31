"""维护可直接发送给 Chat Completions API 的完整对话历史。"""

from typing import Any


class Context:
    """保存 user、assistant 和 tool 消息，并校验工具调用配对。"""

    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.messages: list[dict[str, Any]] = (
            [dict(message) for message in messages]
            if messages is not None
            else []
        )
        if messages is not None:
            self.assert_paired()

    def append_user(self, text: str) -> None:
        """追加用户文本消息。"""
        self.messages.append({"role": "user", "content": text})

    def append_assistant(self, message: dict[str, Any]) -> None:
        """追加完整 assistant 消息，包括 tool_calls。"""
        self.messages.append(message)

    def append_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        """追加与上一条 assistant tool_calls 对应的 tool 消息。"""
        self.messages.extend(tool_results)

    def assert_paired(self) -> None:
        """校验每个 assistant tool_call 都有唯一匹配的 tool result。"""
        pending_ids: set[str] = set()
        seen_ids: set[str] = set()

        for message in self.messages:
            role = message.get("role")
            if role not in {"user", "assistant", "tool"}:
                raise RuntimeError(f"未知消息角色: {role}")

            if role == "assistant":
                if pending_ids:
                    raise RuntimeError("上一轮 tool_calls 缺少对应的 tool result")
                for tool_call in message.get("tool_calls") or []:
                    tool_call_id = tool_call.get("id")
                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        raise RuntimeError("tool_call 缺少有效 id")
                    if tool_call_id in seen_ids:
                        raise RuntimeError(f"tool_call id 重复: {tool_call_id}")
                    pending_ids.add(tool_call_id)
                    seen_ids.add(tool_call_id)
                continue

            if role == "user":
                if pending_ids:
                    raise RuntimeError("tool_calls 后出现了普通 user 消息")
                continue

            tool_call_id = message.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                raise RuntimeError("tool result 缺少有效 tool_call_id")
            if tool_call_id not in pending_ids:
                raise RuntimeError(
                    f"tool result 没有匹配的 tool_call: {tool_call_id}"
                )
            pending_ids.remove(tool_call_id)

        if pending_ids:
            missing = ", ".join(sorted(pending_ids))
            raise RuntimeError(f"对话结束时仍有未配对的 tool_call: {missing}")
