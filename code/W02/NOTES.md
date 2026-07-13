# W02 Session 1

## Tool Use 时序图

请先在纸上手画，再把照片放入当前目录，并将下面的占位路径替换成实际文件名：

> 手绘图待补：`code/W02/session1-tool-use-flow.png`

核心时序：

```text
user
  -> assistant(tool_use)
  -> user(tool_result)
  -> assistant(text)
```

## 本次代码

核心代码：`tools/manual_loop.py`

它只完成一次最小闭环：

1. 第一次请求携带 `tools`。
2. 模型返回 `stop_reason == "tool_use"` 和 `tool_use` block。
3. 本地执行 `get_weather` mock 工具。
4. 手工构造 `tool_result`，并用 `tool_use_id` 配对。
5. 第二次请求携带完整的 assistant/tool_result 消息。
6. 模型返回最终自然语言回答。
