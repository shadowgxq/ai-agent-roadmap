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

LangGraph 的复杂任务默认步骤执行器和步骤 Verifier 仍是演示替身；真实文件修改与测试需注入宿主适配器。图的 Reactive 分支也必须通过 Goal completion gate；缺少可执行标准的默认 manual Goal 保持待复核，不因目录枚举或演示步骤成功就宣称任务完成。节点的活动执行时间累计保存到 checkpoint，普通步骤、Reactive 分支及终态均检查预算；宿主 StepRunner 仍须在每次工具调用前执行自己的额度和超时限制，图的步骤边界检查不提供中途强制终止。

Long-horizon 报告以 `kind` 区分实测、估算和固定参考轨迹。`build_reference_long_horizon_eval()` 返回 `fixture`，不通过正式 readiness gate；缺少来源的历史 JSON 保守读取为 `estimate`。转换为 W18 对照观测时保留来源，不把参考轨迹升级成实测成功。

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

Worker 结果统一使用 `WorkerResult`，Manager 通过 `Manager.evaluate_result()` 返回 `accept`、`retry`、`reassign` 或 `pause`，没有 evidence 的成功结果不会被接受。计划向 Worker 传递实际目标和验收条件；依赖结果由执行器传递。改派仅支持同角色替代 Worker。

## W18 Session 3：Agent Routing

`multi_agent/routing.py` 将“谁来做”从 Manager 的隐式判断变成可观测契约：

- `DeterministicRouter` 先按明确的 `search → Researcher`、`edit → Coder`、`verify → Tester` 规则路由。
- `StructuredRouter` 只接收结构化的 `worker_role`、`reason`、`confidence` 和 `fallback`，非法或低置信度结果会降级到 Manager review。
- `TaskRouter` 在确定性规则未命中且没有安全结构化结果时，返回 `manager_review`，不会把未知任务直接交给任意 Worker。
- `RoutingTrace` 保留每次路由的方式、理由、置信度、fallback 和失败原因；`Manager.recover_route()` 负责 review、blocked 或明确改派。

本 Session 只负责角色选择与失败恢复，不启动 Worker、不执行并行，也不改变 Session 2 的依赖链。

路由同时检查修改与独立验证需求；复合任务须先拆分。未知任务未经明确修改声明不能分配给 Coder。`recover_route(..., reassign_to=..., clarified_request=...)` 要求补充同一任务的明确类型；blocked 决策不能直接改派绕过。10 个路由输入和预期结果位于 `evals/cases/w18_session_03.json`，样例本身不代表运行通过。

## W18 Session 4：依赖图与受限并发

`dependency.py` 校验 DAG 并计算 ready 节点、并行安全性和估算关键路径。`execution.py` 并行调度独立的只读 Researcher，Coder/Tester 独占执行，限制 attempt 与工具预算，按 task/attempt 去重。Worker 必须通过 `WorkerContext.call_tool()` 使用宿主注册的工具。超时撤销后续调用权限；未停止线程仍占用槽位，未知写副作用会隔离工作区。该机制依赖合作式宿主适配器，不提供进程级沙箱。

## W18 Session 5：证据仲裁

`aggregation.py` 将 claim 与当前 attempt/evidence、独立 Tester 验证绑定。竞争结论无法排除时返回调查请求或 review；`build_cache_database_conflict()` 提供缓存/数据库冲突样例。Coder 必须配置 `before_write`，可由当前依赖结果生成聚合报告，再调用 `report.write_decision(assignment, dependencies)`；未提供审查或审查未通过时阻塞写入。

## W18 Session 6：配对评估

`eval.py` 复用 Session 1 的冻结任务，对配对观测比较成功率、成本、端到端耗时、工具调用、上下文和失败率，并返回采用建议。`--mode multi-agent-eval --case-file evals/cases/w18_session_01.json` 只汇总观测；缺少观测或计量时返回 `needs_data`，不会启动 Agent。缺失副作用审计或计量不完整的运行不计为已确认成功。

## 当前交付边界

`multi_agent/workflow.py` 已提供统一非验证流程：W17 Goal → 模型拆分 → 确定性拆分决策 → 路由 → 受控工具/Worker → 证据仲裁 → 有限追加调查 → 授权修改 → 结构化结果。`adapters.py` 复用现有 `AGENT_*` 模型客户端，提供文件读取、搜索、精确替换和宿主生成的证据引用。未选择拆分时使用一个模型 Worker 的工具循环；这不是 W17/W18 配对评估基线运行。

研究阶段只有全部分支声明独立且拆分决策通过时才并发；写入等待仲裁通过。追加调查传递上一轮冲突与证据，再重新仲裁，预算耗尽或分歧未解决时暂停写入。跨阶段共享模型调用、工具调用和 attempt 总预算。

```bash
# 只读分析；需预先配置 AGENT_MODEL / AGENT_API_KEY / AGENT_BASE_URL
uv run advanced-coding-agent "分析接口慢的原因" --mode multi-agent --workdir .

# 允许修改明确文件；测试与验收仍不执行
uv run advanced-coding-agent "修复配置读取" --mode multi-agent --workdir . \
  --write-path src/config.py --criterion "配置兼容原有格式"

# 读取已有 W17 Goal JSON
uv run advanced-coding-agent --mode multi-agent --goal-file goal.json --workdir .
```

`--write-path` 是精确文件白名单；未提供则只读。工具拒绝越界、符号链接及 `.git`/`.env` 等敏感路径，不提供任意 shell。已有文件须先读取，再以唯一原文片段替换；宿主路径保护适用于合作式本地运行，不是操作系统沙箱。

输出包括 Goal、拆分理由、路由、角色输入/输出、各阶段执行记录、调查仲裁、变更文件及证据。非验证流程完成返回 `pending_verification`，退出码 0 仅代表该流程完成；`verification.verified_success` 保持 false。冲突、预算耗尽或未知副作用返回 blocked/needs_review，且不会自动重放写入。

测试、最终 verifier 和 Session 6 批量配对评估不属于此非验证入口，不自动启动。仓库中的 10 个 Session 1 case 是冻结的任务描述与拆分预期，不等于 10 次真实 coding 对照运行。路由正确率、并行实际提速、超时恢复以及 single/multi-agent 的完整实测对照仍待执行验收，不能仅根据模块存在或理论耗时认定 W18 完成。
