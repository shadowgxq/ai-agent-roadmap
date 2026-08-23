# Agent Event Protocol v1

Agent Runtime 通过公共事件协议连接 CLI/Web Adapter。日志事件不属于本协议，
`compact_usage` 等内部观测事件也不能直接进入 SSE。

## Envelope

每个事件都使用同一个 envelope：

```json
{
  "sequence": 0,
  "run_id": "run_123",
  "event": "text",
  "data": {}
}
```

- `sequence`：同一个 `run_id` 内从 `0` 开始递增，用于排序和去重。
- `run_id`：事件所属 Run。
- `event`：公共事件名称。
- `data`：与事件类型对应的 payload。

v1 公共事件包括：`status`、`text`、`tool_call`、`tool_result`、`diff`、`context_usage`、`done`。

## status

Run 的非终态生命周期事件。每次运行会先发布 `queued`，后台执行开始后发布
`running`；策略命令需要用户批准时暂停为 `waiting_confirmation`。其中等待确认的
事件会携带命令、原因和一次性 `confirmation_id`，Web/CLI Adapter 通过确认接口恢复它。

```json
{
  "sequence": 2,
  "run_id": "run_123",
  "event": "status",
  "data": {
    "status": "waiting_confirmation",
    "message": "命令等待用户确认",
    "confirmation_id": "confirm_abc",
    "command": "git clean -fd",
    "reason": "命令可能删除未跟踪文件"
  }
}
```

## text

Assistant 在一次模型调用中产生的文本。

```json
{
  "sequence": 0,
  "run_id": "run_123",
  "event": "text",
  "data": {
    "turn": 1,
    "text": "我先读取配置文件。"
  }
}
```

## tool_call

Agent 请求执行一个或多个工具。`tool_use_id` 是一次工具调用的唯一关联键。

```json
{
  "sequence": 1,
  "run_id": "run_123",
  "event": "tool_call",
  "data": {
    "turn": 1,
    "calls": [
      {
        "tool_use_id": "call_abc",
        "name": "read_file",
        "arguments": "{\"path\":\"README.md\"}"
      }
    ]
  }
}
```

## tool_result

工具执行结果。每个结果必须使用对应 `tool_call` 的同一个 `tool_use_id`。
`is_error=true` 表示参数错误、超时、策略阻止或工具自身异常等失败结果。
重复的 `tool_use_id` 或没有待处理调用与之对应的结果属于协议错误。

```json
{
  "sequence": 2,
  "run_id": "run_123",
  "event": "tool_result",
  "data": {
    "turn": 1,
    "results": [
      {
        "tool_use_id": "call_abc",
        "content": "# agent-mini",
        "is_error": false
      }
    ]
  }
}
```

## diff

文件工具完成写入或编辑后发送结构化 Diff。Diff 与产生它的工具调用保持同一轮次，
前端按 `path` 展示文件状态、增删行和可折叠的 unified patch；二进制文件只保留元信息。

```json
{
  "sequence": 3,
  "run_id": "run_123",
  "event": "diff",
  "data": {
    "turn": 1,
    "files": [
      {
        "path": "src/main.py",
        "status": "modified",
        "patch": "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-print('old')\n+print('new')",
        "additions": 1,
        "deletions": 1,
        "binary": false,
        "truncated": false
      }
    ]
  }
}
```

## context_usage

一次模型调用后的上下文窗口使用情况。Provider 不返回用量时，token 和百分比为
`null`，并设置 `available=false`。

```json
{
  "sequence": 3,
  "run_id": "run_123",
  "event": "context_usage",
  "data": {
    "turn": 1,
    "context_tokens": 3200,
    "context_window_tokens": 128000,
    "context_usage_percent": 2.5,
    "available": true
  }
}
```

## done

唯一终态事件。收到 `done` 后，该 Run 不再产生公共事件，SSE 可以关闭。

终态只允许：

- `completed`：正常完成。
- `failed`：执行失败，可带 `error`。
- `max_turns`：达到最大轮数，必须带 `max_turns`。
- `cancelled`：任务被取消。

```json
{
  "sequence": 4,
  "run_id": "run_123",
  "event": "done",
  "data": {
    "status": "completed",
    "turn": 2,
    "finish_reason": "stop"
  }
}
```

失败示例：

```json
{
  "sequence": 4,
  "run_id": "run_123",
  "event": "done",
  "data": {
    "status": "failed",
    "error": "model request failed"
  }
}
```

## Extension policy

- `compact_usage` 是内部观测事件，由 Web Adapter 明确过滤。
- 未知事件属于协议错误，不能通过类型转换静默进入 SSE。
- v1 不单独发布 `error`；失败统一由 `done(status="failed")` 表达。
- 新增生命周期或确认动作时，必须同时更新 Python 校验、TypeScript 校验、本文档和直接消费者。
