from typing import Any


class Context:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def append_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def append_assistant(self, content: list[dict[str, Any]]) -> None:
        self.messages.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def append_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

    def assert_paired(self) -> None:
        pending_ids: set[str] = set()
        seen_tool_use_ids: set[str] = set()

        for message in self.messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"}:
                raise RuntimeError(f"未知消息角色: {role}")

            if isinstance(content, str):
                if pending_ids:
                    raise RuntimeError("tool_use 后缺少对应的 tool_result")
                continue
            if not isinstance(content, list):
                raise RuntimeError("消息 content 必须是字符串或 block 列表")

            if role == "assistant":
                if pending_ids:
                    raise RuntimeError("上一轮 tool_use 缺少对应的 tool_result")

                for block in content:
                    if not isinstance(block, dict):
                        raise RuntimeError("assistant content block 必须是字典")
                    if block.get("type") != "tool_use":
                        continue

                    tool_use_id = block.get("id")
                    if not isinstance(tool_use_id, str) or not tool_use_id:
                        raise RuntimeError("tool_use 缺少有效 id")
                    if tool_use_id in seen_tool_use_ids:
                        raise RuntimeError(f"tool_use id 重复: {tool_use_id}")

                    pending_ids.add(tool_use_id)
                    seen_tool_use_ids.add(tool_use_id)
                continue

            tool_results = [
                block
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "tool_result"
            ]
            if not tool_results:
                if pending_ids:
                    raise RuntimeError("tool_use 后出现了普通 user 消息")
                continue
            if not pending_ids:
                raise RuntimeError("tool_result 没有对应的 tool_use")

            result_ids: set[str] = set()
            for block in tool_results:
                tool_use_id = block.get("tool_use_id")
                if not isinstance(tool_use_id, str) or not tool_use_id:
                    raise RuntimeError("tool_result 缺少有效 tool_use_id")
                if tool_use_id in result_ids:
                    raise RuntimeError(f"tool_result id 重复: {tool_use_id}")
                if tool_use_id not in pending_ids:
                    raise RuntimeError(
                        f"tool_result 没有匹配的 tool_use: {tool_use_id}"
                    )
                result_ids.add(tool_use_id)

            missing_ids = pending_ids - result_ids
            if missing_ids:
                missing = ", ".join(sorted(missing_ids))
                raise RuntimeError(f"部分 tool_use 缺少结果: {missing}")
            pending_ids.clear()

        if pending_ids:
            missing = ", ".join(sorted(pending_ids))
            raise RuntimeError(f"对话结束时仍有未配对的 tool_use: {missing}")
