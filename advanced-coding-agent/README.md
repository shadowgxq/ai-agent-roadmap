# advanced-coding-agent

W16–W18 的独立 Coding Agent 实验项目，不复用 `agent-mini` 的运行时代码。

路线固定按下列顺序递进：

```text
W16  v1  Planning：Plan → Executor → Verifier → Re-plan
  ↓
W17  v2  Long-horizon：Goal + Progress + Context + Recovery
  ↓
W18  v3  Multi-Agent：Manager + Researcher/Coder/Tester
```

项目保留同一套 Reactive baseline，并在其上逐版增加复杂度：W16 先完成 Planning 闭环；W17 在 v1 上加入 Long-horizon 的目标、进度、上下文与恢复；W18 再在 v2 上引入 Multi-Agent 协作。复杂任务默认进入 LangGraph，Planner 通过 LangChain structured output 生成计划；`--planner-backend deterministic` 可运行确定性基线。

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

Planning 使用 `AGENT_MODEL`、`AGENT_API_KEY` 和 `AGENT_BASE_URL` 配置；LangGraph 负责节点编排和 thread checkpoint，LangChain Planner 只生成计划，不执行工具，领域代码继续负责校验和状态迁移。

## 本地运行

```bash
uv sync
uv run advanced-coding-agent "查找仓库中的配置文件" --workdir .
uv run advanced-coding-agent "修复登录失败并运行测试" --mode planning --workdir .
```

Planning 输出包含分类、Plan、当前步骤、步骤结果、验证状态、re-plan 次数和 graph status。`--planner-backend llm` 保留旧版直接 Planner，便于对照。
