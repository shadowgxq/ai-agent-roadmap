# advanced-coding-agent

W16–W18 的独立 Coding Agent 实验项目，不复用 `agent-mini` 的运行时代码。

项目同时保留 Reactive baseline 和 Planning 模式：复杂任务默认交给 LLM Planner 生成结构化计划，`--planner-backend deterministic` 可运行确定性基线。

## 目录边界

```text
advanced-coding-agent/
├── src/advanced_coding_agent/
│   ├── contracts.py       # 稳定的任务与运行基础契约
│   ├── classification.py  # Session 1 任务复杂度与 Planning 候选门槛
│   ├── runtime/           # Reactive / Planning 运行控制流
│   ├── tools/             # 仓库读写、搜索和命令工具适配
│   ├── planning/          # W16 Plan 与 Planner
│   └── verification/      # W16 Verifier 与证据判断
└── evals/cases/           # 固定任务与对照样例
```

LLM Planning 使用 `AGENT_MODEL`、`AGENT_API_KEY` 和 `AGENT_BASE_URL` 配置；模型只生成计划，不执行工具，计划仍由代码校验。

## 本地运行

```bash
uv sync
uv run advanced-coding-agent "查找仓库中的配置文件" --workdir .
```

输出包含任务分类、是否建议启用 Planning、工具结果、工具调用成功率和重复工作次数。固定的 Session 1 简单/复杂任务位于 `evals/cases/session_01.json`。
