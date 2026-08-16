评分时必须覆盖这些事实：

- src/loop.py 负责驱动模型决策、工具调用和消息回填的循环。
- src/context.py 保存配对的消息历史，供下一轮模型调用使用。
- src/tools.py 定义 ToolRegistry，把工具 schema 暴露给模型并统一执行入口。
- src/mcp_adapter.py 把外部 MCP 工具转换成内部注册表格式，并负责远程调用路由。
- 一次工具调用的顺序是：模型产生 tool call、Registry 执行、结果写回 Context、Loop 再次调用模型。
- Agent Loop 不应该直接判断工具来自本地 Python 还是 MCP。
