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
│   ├── verification/      # W16 Verifier 与证据判断
│   └── multi_agent/       # W18 拆分决策与角色边界
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

## W18 Session 1：拆分决策

Session 1 先冻结 W17 single-agent v2 的模型、工具、上下文、调用次数、超时和成功指标，再根据任务的并行收益、上下文隔离、专业工具、权限隔离和独立验证证据决定是否拆分：

```bash
uv run advanced-coding-agent \
  --mode split-decision \
  --case-file evals/cases/w18_session_01.json
```

输出包含估算关键路径、扣除协调开销后的 latency projection、拆分理由、Worker 边界和 Manager/Worker/State/Evidence 数据流。该结果只是架构决策和估算，不代表真实并发测量；Manager/Worker 执行、路由与并行留给后续 Session。

## W18 Session 2：Manager / Worker 契约

`multi_agent/collaboration.py` 在 Session 1 的边界上增加固定角色 Prompt、工具白名单、超时和调用预算，并由 `Manager.create_plan()` 生成 `Researcher → Coder → Tester` 的结构化任务链。`CollaborationTrace` 记录 assignment、result 和 Manager decision；它不会启动模型或工具。

Worker 结果统一使用 `WorkerResult`，Manager 通过 `Manager.evaluate_result()` 返回 `accept`、`retry`、`reassign` 或 `pause`，没有 evidence 的成功结果不会被接受。动态路由、并行执行和冲突聚合留给后续 Session。
