"""维护可直接发送给 Messages API 的完整对话历史。"""

from typing import Any


class Context:
    """保存标准字典格式的 user、assistant 和 tool_result 消息。"""

    def __init__(self) -> None:
        """创建一个空的对话上下文。"""
        self.messages: list[dict[str, Any]] = []

    def append_user(self, text: str) -> None:
        """追加用户输入的普通文本消息。"""
        self.messages.append({"role": "user", "content": text})

    def append_assistant(self, content: list[dict[str, Any]]) -> None:
        """追加模型返回的完整 content blocks，不能只保存 text。"""
        self.messages.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def append_tool_results(self, tool_results: list[dict[str, Any]]) -> None:
        """把本轮所有工具结果合并成一条 user 消息。

        Messages API 规定 tool_result 使用 user 角色，并通过 tool_use_id
        与上一条 assistant 消息里的 tool_use.id 配对。
        """
        self.messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

    def assert_paired(self) -> None:
        """校验工具调用与结果是否完整、唯一并按协议顺序出现。

        该方法只检查已有历史，不修改消息；发现缺失、重复、越序或无法匹配
        的 ID 时立即抛出 RuntimeError。
        """
        # pending_ids 保存当前等待结果的工具调用；正常完成一轮后必须清空。
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

            # assistant 的 tool_use 开启一组待配对调用。
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

            # user 的 tool_result 关闭上一条 assistant 开启的调用。
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
