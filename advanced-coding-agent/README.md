# advanced-coding-agent

W16–W18 的独立 Coding Agent 实验项目，不复用 `agent-mini` 的运行时代码。

当前已完成 W16 Session 1 的 Reactive baseline：先分类任务，再读取仓库根目录、执行一个工具并输出结构化结果；不创建 Planner，也不执行多步循环。

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

Session 1 基线不调用真实模型；模型配置在后续需要时再接入。

## 本地运行

```bash
uv sync
uv run advanced-coding-agent "查找仓库中的配置文件" --workdir .
```

输出包含任务分类、是否建议启用 Planning、工具结果、工具调用成功率和重复工作次数。固定的 Session 1 简单/复杂任务位于 `evals/cases/session_01.json`。
