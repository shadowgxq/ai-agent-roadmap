# AI Agent 通用模板：技术设计与实现规范

> 版本：v1.0 · 日期：2026-09-15 · 文档性质：公共技术内核设计  
> 适用范围：当前 `ai-agent-roadmap` 中后续新增的可恢复、可观测、可扩展 Python Agent 工作流  
> 核心技术：LangGraph + LangChain + PostgreSQL Checkpoint + Langfuse  
> 不包含：前端、HTTP 服务、消息队列、部署平台、具体业务领域规则

---

## 1. 结论先行

当前项目已经具备几块可以组合的通用能力，但还不是一个可以直接作为公共库发布的统一 Agent Runtime：

- `advanced-coding-agent` 已经实现了 Plan、Replan、Recovery、Completion Gate 以及有边界的 Multi-Agent 执行模型。
- `support-agent` 已经实现了 LangGraph 的 PostgreSQL checkpoint 生命周期、`thread_id` 续跑和 `Command(resume=...)` 人工恢复。
- `agent-mini` 已经实现了模型/工具循环、有限重试、原子 JSON 快照、成本估算以及 Langfuse 手工 tracing。
- 这些能力的状态模型、错误模型、日志模型和运行入口尚未统一，不能直接把三个项目的内部包互相 import 后称为公共框架。

因此，推荐新建一个**独立的公共 AI Agent 模板层**，业务模块只依赖它的稳定契约：

```text
业务 Skill / 业务 Graph
        │
        ▼
公共 Agent Runtime
  ├─ 执行模式：reactive / plan / multi-agent
  ├─ 统一状态：Run / Plan / Task / Attempt / Evidence
  ├─ 错误边界：分类 → 有限重试 / 重规划 / 对账 / 人工介入
  ├─ 持久化：LangGraph Checkpoint + 业务 Artifact / Operation Ledger
  ├─ 可观测性：Langfuse trace/span/generation/tool/retry
  └─ 完成门禁：确定性检查 + 证据约束的语义复核
```

公共模板不负责“研究什么”，只负责“如何安全、可恢复地执行一套研究或分析流程”。

---

## 2. 当前项目实现基线

### 2.1 已有能力与实际路径

| 能力 | 当前实现 | 真实状态 | 公共模板处理 |
|---|---|---|---|
| LangChain 结构化输出 | `advanced-coding-agent/src/advanced_coding_agent/planning/langchain_planner.py:25-116` | 已有 Pydantic 计划 schema、模型输出校验、计划领域校验 | 提取为 `StructuredOutputPort`，业务 schema 外置 |
| Plan 执行状态 | `advanced-coding-agent/.../planning/execution.py:190-527` | 有当前步骤、依赖、步骤结果、blocked/failed/completed、checkpoint-safe 序列化 | 作为通用 Plan Domain 的参考实现 |
| Replan | `advanced-coding-agent/.../planning/replan.py:25-337` | 证据触发、有限重规划、保留计划历史、工具/时间/次数预算 | 提取 `ReplanPolicy`，不绑定 Coding 领域 |
| Recovery | `advanced-coding-agent/.../long_horizon/recovery.py:132-562` | failure event、retry/replan/reconcile/resume/manual_review/blocked、版本一致性 | 作为统一错误决策层 |
| Completion Gate | `advanced-coding-agent/.../long_horizon/completion.py:70-451` | 区分步骤验证与全局成功，确定性条件和证据约束语义条件 | 作为所有业务的最终门禁 |
| LangGraph Plan 图 | `advanced-coding-agent/.../planning/graph.py:231-1309` | 已把领域状态接入 LangGraph，含 classify/planner/select/execute/verify/replan/completion | 仅复用流程思想，修正命名和依赖注入后再抽象 |
| Multi-Agent 拆分决策 | `advanced-coding-agent/.../multi_agent/decision.py:70-422` | 用可见规则判断 single-agent/multi-agent，定义 manager/researcher/coder/tester 边界 | 作为通用分流策略起点 |
| Multi-Agent 执行 | `advanced-coding-agent/.../multi_agent/execution.py:56-833` | 有依赖 DAG、并发上限、WorkerContext、工具权限、尝试身份、超时、隔离和重试安全判定 | 作为本地 bounded executor 参考；不宣称分布式 exactly-once |
| 证据聚合 | `advanced-coding-agent/.../multi_agent/aggregation.py:39-299` | claim 绑定 task/attempt/evidence，独立验证，冲突不投票，支持 investigate/needs_review | 适合研究、审查和多角色分析的共享聚合器 |
| PostgreSQL Checkpoint | `support-agent/src/support_agent/persistence/checkpointer.py:9-19` | `AsyncPostgresSaver.from_conn_string()`、`await setup()`、上下文生命周期 | 作为默认生产 checkpointer 工厂 |
| LangGraph 续跑 | `support-agent/src/support_agent/services/runner.py:16-96` | `thread_id`、`aget_state`、`ainvoke(None)`、`Command(resume=...)` | 作为 Runner API 参考 |
| 模型/工具循环 | `agent-mini/src/agent/loop.py:1021-1158`、`1260-1343` | OpenAI 兼容请求、有限网络重试、工具调用结果、checkpoint callback | 提取为模型与工具端口，不把循环状态继续留在 JSON 文件 |
| Langfuse | `agent-mini/src/agent/runtime.py:265-525`、`agent-mini/src/agent/loop.py:1048-1127` | root observation、generation、usage、metadata、flush；主链是手工 SDK tracing，不是 LangChain CallbackHandler | 提取为公共 `ObservabilityPort`，并增加 fail-open 和隐私策略 |
| 成本估算 | `agent-mini/src/agent/cost.py:302-453` | 按 Agent/compact/router/judge 用量和价格表估算，缺价格时不可用 | 只能作成本估算；业务硬预算需要调用前预留 |
| JSON 快照 | `agent-mini/src/agent/checkpoint.py:172-204` | 原子写临时文件、fsync、os.replace | 作为 CLI 崩溃保护参考，不与 LangGraph Checkpoint 并列为主事实源 |

### 2.2 已发现的实现缺口

1. `advanced-coding-agent/planning/graph.py:249` 的 `self.planner = planner` 与 `planner()` 方法同名；应改为 `self.planner_service`、`plan_node()`，避免实例属性遮蔽方法。
2. `advanced-coding-agent` 的图默认使用 `InMemorySaver`，只能作为示例默认值；公共模板必须显式注入持久化 saver。
3. `support-agent` 的 `max_run_cost_usd` 目前主要是配置字段，不能直接当作完整的调用前预算熔断。
4. `agent-mini` 的 Langfuse 已接入主链，但 Langfuse 初始化、update、flush 的异常隔离和敏感信息过滤还不够完整；不能将“有 trace”直接等价为生产级观测闭环。
5. `agent-mini` 的 JSON snapshot 与 LangGraph checkpoint 解决的是不同层面的问题；公共模板只能选一个主恢复事实源，不能让两套快照互相覆盖。
6. Multi-Agent executor 是进程内线程池调度器，超时只能撤销后续工具权限，不能杀死已经运行的 Python 线程，也不能撤销已经发生的外部副作用。

---

## 3. 公共模板的分层

### 3.1 六层职责

```text
┌──────────────────────────────────────────┐
│ Domain Layer                             │
│ 业务 Skill、业务对象、研究/客服/编码规则 │
├──────────────────────────────────────────┤
│ Workflow Layer                           │
│ LangGraph 图、节点、路由、子图、门禁     │
├──────────────────────────────────────────┤
│ Execution Layer                          │
│ Plan、Task、Worker、Attempt、预算、重试  │
├──────────────────────────────────────────┤
│ Model & Tool Layer                       │
│ LangChain 模型、结构化输出、工具适配器   │
├──────────────────────────────────────────┤
│ Persistence & Artifact Layer              │
│ Checkpoint、证据、产物、调用台账         │
├──────────────────────────────────────────┤
│ Observability Layer                      │
│ Langfuse、结构化日志、事件、成本         │
└──────────────────────────────────────────┘
```

### 3.2 严格边界

- **LangGraph**：负责状态推进、节点依赖、分支、join、interrupt 和 checkpoint。
- **LangChain**：负责模型统一接口、结构化输出、客户端工具调用和模型 provider 适配。
- **业务 Skill**：负责方法论、问题清单、输出 schema 和领域质量规则。
- **公共 Runtime**：负责如何执行、失败后怎样恢复、如何记录和何时停止。
- **确定性代码**：负责 ID、预算、时间、单位、权限、哈希、数字计算和硬门禁。
- **模型**：负责有限范围内的规划、抽取、解释和语义评估，不能绕过代码门禁。

公共 Runtime 不应该知道“公司研究”或“客服工单”的字段；业务模块不应该直接操作 checkpointer 内部表，也不应该手写一套重试循环。

---

## 4. 三种通用执行模式

### 4.1 Reactive 模式：简单任务快速路径

```text
输入
 → 能力/权限检查
 → 一次模型或工具调用
 → 结构化结果校验
 → 完成门禁
 → 输出
```

适合：单次分类、只读问答、简单格式转换、无需多步骤依赖的任务。

规则：

- 不为了形式使用 Planner。
- 即使是 Reactive，也必须有 `RunManifest`、调用记录、错误分类和最终状态。
- 失败时不能静默转成“模型不知道”；按错误矩阵返回 `failed`、`blocked` 或 `needs_review`。

本地参考：`advanced-coding-agent/planning/graph.py:281-298` 的 `reactive()` 仅是领域示例，默认执行器仍是演示性质，公共模板需要替换为业务注入的 runner。

### 4.2 Plan 模式：长任务的默认通用模式

```text
classify
  ├─ simple → reactive
  └─ complex
       ↓
planner
       ↓
validate_plan
       ↓
select_step
       ↓
execute_one_step
       ↓
verify_step
       ├─ pass → select_step / completion
       ├─ transient failure → bounded retry
       ├─ verification failure → repair / replan
       ├─ plan invalidated → replan
       ├─ unknown external result → reconcile / manual review
       └─ terminal → blocked / failed
       ↓
completion_gate
       ├─ succeeded → done
       ├─ failed → repair / replan
       └─ needs_review → interrupt / blocked
```

#### Plan 的硬规则

1. 计划由结构化 schema 表示，不接受模型输出的一段自然语言清单。
2. 每个步骤必须有稳定 `step_id`、完成条件、依赖和允许工具。
3. 每次只领取一个步骤或一组明确无依赖、无共享写入的步骤。
4. 步骤最终结果必须包含 summary、evidence_refs、verification 状态和失败原因。
5. `completed` 的步骤不能因为普通恢复而被重复执行；需要重做时产生新 attempt 或新 plan version。
6. Planner 只能制定计划，不能在同一节点偷偷执行工具。
7. 最后一步成功不等于整个 Goal 成功，必须经过 Completion Gate。

#### 计划状态

```text
Plan:
  goal_id / goal_version / plan_version
  constraints / available_tools
  steps[id, description, dependencies, status, evidence_refs]

PlanExecutionState:
  current_step
  step_results
  status: pending | running | completed | failed | blocked
  blocked_reason
  last_recovery
```

本地参考：`planning/execution.py:190-527` 已经把这些状态做成 checkpoint-safe 的领域对象；后续公共化时保留它的验证逻辑，但把 `workdir`、文件变更等编码字段改成泛化的 Artifact/Effect 契约。

### 4.3 Multi-Agent 模式：有理由才拆分

Multi-Agent 不是“多开几个模型调用”。只有满足并行、上下文隔离、专业化、权限隔离或独立验证之一，才考虑拆分。

```text
Manager / Lead
  ├─ Researcher A：只读、独立上下文
  ├─ Researcher B：只读、独立上下文
  ├─ Specialist：受限工具与角色边界
  └─ Tester / Verifier：独立验证
        ↓
Task Result Aggregator
        ↓
Evidence / Conflict Aggregator
        ↓
Completion Gate
```

#### Multi-Agent 的通用原则

- Manager 分配任务，不默认拥有所有工具。
- Worker 只接收最小必要上下文和预算；不共享全部 messages。
- 共享写入集中在单一 Writer/Coder，不能多个 Worker 同时改同一目标。
- 研究型 Worker 默认只读；验证型 Worker 不能验证自己刚生成的结论。
- 每个逻辑任务都有 `task_id`，每次执行有递增 `attempt_number` 和唯一 `attempt_id`。
- 聚合器按 task/attempt 身份去重，不按到达顺序覆盖。
- 语义冲突不使用多数投票；必须保留候选结论、证据、反证和未解决状态。
- 超时不能被解释为 Worker 已经停止；若存在写入或外部副作用可能，工作区/任务进入隔离或对账。

本地参考：

- `multi_agent/decision.py:328-512` 负责“是否应该拆分”的可见规则。
- `multi_agent/execution.py:432-706` 是进程内有界 DAG 调度器。
- `multi_agent/aggregation.py:156-299` 采用证据绑定、独立验证和冲突保留，不把投票当成事实判定。

#### LangGraph 中的 Multi-Agent 汇合

固定角色建议使用固定父节点并显式 join：

```python
builder.add_edge(["researcher_a", "researcher_b", "verifier"], "aggregate")
```

动态任务才使用 `Send`。并行分支共享同一字段时必须配置 reducer，或者每个分支写独立字段。不要用普通四条入边模拟 barrier，也不要依赖结果返回顺序。

---

## 5. 统一领域契约

### 5.1 RunManifest

```text
run_id / request_id / thread_id
workflow_id / workflow_version / graph_version
skill_id / skill_version / skill_hash
model_id / provider / endpoint_id / adapter_version
start_at / as_of / timezone
budget_policy / authorization_policy
parent_run_id / report_revision
```

所有恢复都以 RunManifest 为版本锚点。图、Skill、schema、模型适配协议发生不兼容变化时，不能直接在旧 thread 上恢复。

### 5.2 Task / Attempt

```text
Task:
  task_id / assignment_id / role / objective / dependencies
  tool_allowlist / input_refs / success_criteria / idempotency_key

Attempt:
  attempt_id / task_id / attempt_number / worker_id
  started_at / finished_at / timeout / tool_call_ids
  outcome_known / side_effect_status / evidence_refs
  status / failure_reason
```

`idempotency_key` 只用于帮助去重，不能证明外部系统 exactly-once。外部副作用未知时，必须进入 reconcile 或人工复核。

### 5.3 Evidence 与 Artifact

公共模板不限定证据内容类型，但要求所有业务结果引用不可变产物：

```text
Artifact:
  artifact_id / artifact_type / content_hash / schema_version
  created_by_run / created_by_attempt / input_refs
  created_at / immutable

EvidenceRef:
  evidence_id / artifact_id / locator / quote_or_summary
  source / retrieved_at / temporal_status
```

大文本不进入图 state；state 只保存 `artifact_id`、`evidence_id` 和小型摘要。

### 5.4 CompletionResult

```text
status: succeeded | failed | needs_review
summary
evaluations[criterion_id, status, evidence_refs, checks]
failed_criteria / review_criteria
requires_manual_intervention
```

`StepResult` 回答“这一步是否完成”；`CompletionResult` 回答“整个目标是否达到所有冻结的成功标准”。二者不能合并成一个 `success: bool`。

---

## 6. 错误边界与重试设计

### 6.1 错误分类

```text
TransportError       连接、DNS、读取超时、429、5xx
ProviderProtocolError HTTP 成功但工具块报错、响应截断、协议字段无效
ModelOutputError     结构化输出不合法、字段缺失、无法解析
ToolError            工具参数/权限/业务执行失败
VerificationError    步骤或完成条件未通过
PlanInvalidatedError 新证据使计划假设失效
PersistenceError     checkpoint / artifact / ledger 持久化失败
UnknownExternalError 请求可能发生但结果未知
InterruptControl     人工中断，不属于普通失败
```

错误对象必须包含安全的摘要、节点、task/attempt/operation ID、可恢复性和证据引用，不能将密钥、全量提示词或原始私密响应写入普通日志。

### 6.2 RecoveryAction

```text
retry              当前操作可安全有限重试
replan             当前计划失效，生成新版本
reconcile          外部结果未知，先对账
resume_checkpoint  从持久化 checkpoint 恢复
manual_review      需要人工判断
blocked            停止推进，等待外部解除
```

本地 `long_horizon/recovery.py:343-467` 的决策优先级值得保留：

- `unknown_external_result` 优先 reconcile，不盲重放。
- `worker_restart` 先校验 checkpoint/run/evidence 版本一致。
- `plan_invalidated` 和 `verification_failure` 进入 replan 或修复。
- tool timeout/database disconnect 才能进入有限 retry。
- 未知异常默认 manual review，不自动伪装成可重试网络错误。

### 6.3 重试层次

公共模板只允许一个主重试层，避免 SDK、LangChain、LangGraph、业务循环叠加：

```text
Provider SDK: max_retries = 0 或纳入统一台账
公共 RecoveryPolicy: 统一判断、退避、attempt、预算
LangGraph RetryPolicy: 只处理节点级明确瞬时异常
业务 Replan: 不计作普通重试，产生新的计划版本
```

推荐基线：

- 首次执行 + 最多两次重试，即 `max_attempts=3`。
- 指数退避 + 抖动，设置最大等待和 run 总截止时间。
- 仅对已知连接、429、5xx、瞬时数据库连接错误重试。
- 401/403、schema 设计错误、参数错误、预算耗尽不重试。
- 已经发出的外部写操作，除非结果已确认且操作幂等，否则不自动重试。
- 每次真实尝试都写入 Attempt/Operation Ledger，并计入预算。

### 6.4 Timeout 的真实语义

- 进程内线程池的 timeout 不能杀死线程。
- timeout 后只能撤销 Worker 后续工具权限；已经进行的调用可能仍在运行。
- 读操作超时且结果确定未知时，可以按策略重试。
- 写操作/外部副作用超时，结果未知，进入 quarantine/reconcile。
- 异步 LangGraph 节点可以配置节点级 timeout，但它不替代 provider 读超时，也不替代 run 总时限。

### 6.5 Interrupt 的边界

`interrupt()` 是控制流，不是 ToolError：

- 不被通用 `except Exception` 转换为失败。
- 恢复使用 `Command(resume=...)`。
- 恢复会从包含 interrupt 的节点开头重新执行，因此节点开始前不能做不可逆副作用。
- 人工问题必须有 question_id、版本和预期 checkpoint，拒绝过期答案。

---

## 7. Checkpoint 设计

### 7.1 默认选型

公共模板默认：

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
    await saver.setup()
    graph = build_graph().compile(checkpointer=saver)
```

`support-agent/src/support_agent/persistence/checkpointer.py:9-19` 已提供相同生命周期模式。

实施时必须锁定实际版本；当前仓库的依赖声明只是范围，不是兼容性验证。`AsyncPostgresSaver.setup()` 属于初始化迁移，不应在每个业务节点中重复调用。

### 7.2 Thread 与 checkpoint

```text
thread_id      一条执行历史容器，公共模板建议一个 run 一个 thread
checkpoint_id  一个具体状态快照
checkpoint_ns  根图/子图命名空间
```

调用：

```python
config = {"configurable": {"thread_id": thread_id}}
await graph.ainvoke(initial_state, config=config, durability="sync")
await graph.ainvoke(None, config=config, durability="sync")
await graph.ainvoke(Command(resume=value), config=config)
```

- `ainvoke(None)` 只适用于原图尚未结束且存在可继续状态。
- 已结束的 `partial/blocked` 不是待执行节点；补跑应创建新 revision/run。
- 显式使用旧 checkpoint_id 是回放/分叉，后续节点可能重新产生模型调用和外部调用。
- 同一个 thread 的 continue/resume 必须串行化。

### 7.3 Durability

| 模式 | 语义 | 通用模板建议 |
|---|---|---|
| `sync` | 下一 super-step 前写完 checkpoint | 默认 |
| `async` | checkpoint 与下一步并行写入 | 性能优化后再启用 |
| `exit` | 退出时才写入 | 不作为长任务崩溃恢复默认 |

Checkpoint 只保存图状态，不自动保存外部请求结果、完整文件或交易/写操作事务。必须配套 Artifact Repository 和 Operation Ledger。

### 7.4 恢复一致性

恢复前校验：

```text
checkpoint.run_id == run.run_id
checkpoint.workflow_version == manifest.workflow_version
checkpoint.goal_version == run.goal_version
evidence.plan_version == checkpoint.plan_version
skill_hash == manifest.skill_hash
```

本地 `long_horizon/recovery.py:534-562` 已实现 checkpoint、run、evidence 三类来源的版本一致性检查思想，应抽取为公共函数。

### 7.5 Pending writes 与 exactly-once

LangGraph 可在同一 super-step 中保留已完成节点的 pending writes，恢复时避免重新执行已成功分支；但它不保证：

- 进程崩溃前未落盘的数据能够找回。
- 供应商请求不会重复计费。
- checkpoint 能回滚外部副作用。
- 整个用户请求 exactly-once。

公共模板必须把外部调用结果先写入 Operation Ledger/Artifact，再把引用写进 checkpoint。响应未知时不盲重发。

---

## 8. Langfuse 可观测性规范

### 8.1 当前项目实际状态

`agent-mini` 已在 `runtime.py:265-313` 建立 root observation：

- 启用条件是 Langfuse 配置和公私钥齐备。
- 使用 `start_as_current_observation(as_type="agent", name="agent-mini.run")`。
- 通过 `propagate_attributes` 传 metadata/tags。
- 结束时更新 output 和 usage/cost metadata。
- 通过 `resource_stack.callback(langfuse_client.flush)` 刷新事件。

`agent-mini/loop.py:1054-1127` 对每次 LLM 调用建立 generation，记录 attempt、模型、输入、输出和 token usage。

这条链是**手工 Langfuse SDK tracing**，不是 `LangChain CallbackHandler`。`support-agent` 当前没有等价的 Langfuse 主链接入。

### 8.2 公共 trace 树

```text
Trace: run_id / workflow_id / thread_id
  ├─ Span: graph.invoke
  │   ├─ Span: node.plan
  │   │   └─ Generation: planner.model
  │   ├─ Span: node.execute
  │   │   ├─ Generation: worker.model
  │   │   └─ Tool: search/read/calculate
  │   ├─ Span: recovery.retry
  │   └─ Span: completion_gate
  └─ Span: report.finalize
```

所有 observation metadata 至少携带：

```text
run_id / request_id / thread_id / workflow_id / node_id
role / task_id / attempt_id / plan_version
model / provider / environment / result_status
```

不把完整 PDF、完整搜索响应、密钥、用户隐私和长消息默认放入 metadata。大内容放 Artifact 引用和 hash。

### 8.3 公共端口

```text
ObservabilityPort:
  start_run(manifest) -> TraceContext
  start_node(ctx, node_id, input_ref) -> SpanContext
  start_generation(ctx, model, attempt) -> GenerationContext
  record_tool(ctx, tool_name, operation_id, status, usage)
  record_retry(ctx, failure_kind, attempt, delay)
  record_checkpoint(ctx, checkpoint_id, phase)
  end_node(ctx, output_ref, status)
  flush()
```

Langfuse 是一个实现，不应让业务代码到处直接 import `Langfuse`。允许 `NoopObservability`，以便离线运行和缺少凭证时继续执行。

### 8.4 Fail-open 与 Fail-closed

- Langfuse 网络/鉴权/flush 失败：默认记录本地结构化日志，业务流程继续；不能因为观测服务不可用伪造业务成功。
- 研究证据、checkpoint、操作台账写入失败：业务流程停止；这些不是可选观测。
- 生产发布策略可以要求“必须存在 Langfuse trace”，此时由完成门禁决定 blocked，而不是在每个业务节点捕获异常。

当前 `agent-mini` 的 Langfuse 异常隔离还需补强，不能直接视为已满足上述 fail-open。

### 8.5 SDK 版本与隐私

公共模板需锁定 Langfuse Python SDK 代际，不混用 v3/v4 示例：

- v4 仍可使用 `from langfuse.langchain import CallbackHandler`，但不传 `update_trace` 参数。
- 新代码优先使用 `start_as_current_observation()` 和 `propagate_attributes()`。
- 如果使用 `mask_otel_spans`，按实际安装 SDK 的类型和签名实现；它只影响该 Langfuse 客户端的导出路径，不等于应用内全局脱敏。
- 脱敏应在发送前进行；日志、Artifact、checkpoint 和其他 OTel exporter 需要分别治理。
- metadata 只放低敏短字段；用户标识使用稳定匿名 ID，不把姓名、手机号等原文当 trace 属性。

### 8.6 本地日志

Langfuse 之外保留结构化 JSONL：

```text
event_id / occurred_at / run_id / node_id / task_id / attempt_id
level / event_type / status / error_kind / artifact_refs
```

日志与 Langfuse 都不记录模型内部思考文本。错误日志使用 `error_type`、安全摘要和关联 ID；不直接打印 API key、Authorization header 或完整供应商 raw response。

---

## 9. 工具与权限边界

### 9.1 ToolSpec

```text
name / description / input_schema
effect: read | write | verify
idempotency_policy
timeout_policy
allowed_roles
sensitivity
```

Worker 只能通过 `WorkerContext.call_tool()` 访问工具。工具实现由宿主注册，模型不能提交 Python callable。

### 9.2 角色权限

通用默认角色：

| 角色 | 默认权限 | 说明 |
|---|---|---|
| manager | 无业务工具 | 拆分、分配、聚合、停机 |
| researcher | read | 只读探索、搜索、读取资料 |
| writer/coder | read + 指定 write | 所有共享写入集中在这里 |
| tester/verifier | read + verify | 独立验证，不能验证自己写的结果 |

业务可定义 `analyst`、`financial_analyst` 等角色，但必须继承一个明确的 effect 边界。

### 9.3 工具调用预算

公共模板同时统计：

- 每个 task 的工具调用数。
- 每个 attempt 的工具调用数。
- 整个 run 的工具调用数。
- 模型 token 和可知费用。
- 未知请求预留。

预算必须在调用前预留；只有调用后确知的用量才能结算。调用未知时保留 `held_unknown`，不当作 0。

---

## 10. Skill 扩展规范

Skill 只描述领域流程，不创建任意代码执行权限：

```text
skills/<skill-id>/
  SKILL.md
  manifest.yaml
  references/
  schemas/
```

最小 manifest：

```yaml
schema_version: "1"
id: example-analysis
version: "0.1.0"
workflow_id: example_workflow
input_schema: ExampleRequestV1
output_schema: ExampleResultV1
allowed_tools: [read_source, calculate]
required_capabilities: [structured_output]
max_gap_rounds: 2
completion_policy: example_release_v1
```

加载流程：

```text
registry lookup
 → safe parse
 → schema validate
 → workflow_id allowlist
 → tool allowlist check
 → skill_hash/policy_hash
 → write RunManifest
```

恢复时使用 manifest 中冻结的 Skill 版本，不自动加载最新文件。网页、报告、用户资料是数据，不是 Skill 指令。

---

## 11. 推荐目录

```text
research-agent/
  pyproject.toml
  src/research_agent/
    contracts.py
    state.py
    runner.py
    graph.py
    errors.py
    settings.py
    skill_loader.py
    models/
      ports.py
      factory.py
    execution/
      plan.py
      retry.py
      workers.py
      aggregation.py
      completion.py
    persistence/
      checkpointer.py
      artifacts.py
      operations.py
    observability/
      ports.py
      langfuse_adapter.py
      logging.py
    tools/
      registry.py
      context.py
  skills/
    shared/
    <domain-skill>/
```

MVP 先把 `research-agent` 建成独立包，不修改 `advanced-coding-agent`、`agent-mini`、`support-agent` 的原有学习代码。后续确认公共契约稳定，再考虑提取共享包。

---

## 12. 实施顺序

### Phase 0：契约和 Noop 运行

实现：`contracts.py`、`state.py`、`errors.py`、`NoopObservability`、一个最小 Reactive 图。

验收：输入、状态、错误、完成状态可序列化；Langfuse 没有凭证时仍可运行。

### Phase 1：Plan 图

实现：

- LangChain structured planner。
- `PlanExecutionState`。
- 单步执行、验证、Completion Gate。
- `RecoveryPolicy` 和有限 retry。
- `AsyncPostgresSaver` 注入与 `thread_id` 续跑。

验收：计划步骤完成、失败、blocked、重试、恢复和完成门禁都能区分；不把最后一步成功当全局成功。

### Phase 2：Langfuse

实现：

- Run root observation。
- Graph node span。
- model generation、tool、retry、checkpoint、completion observation。
- run/task/attempt 关联字段。
- fail-open、mask、日志脱敏。

验收：一条运行能从 Langfuse 根 trace 追到节点、模型调用、工具、重试和最终状态；观测失败不会破坏业务状态。

### Phase 3：Multi-Agent

实现：

- bounded DAG。
- role/tool boundary。
- task/attempt 聚合。
- 超时、unknown side effect、workspace quarantine。
- 独立验证和证据冲突聚合。

验收：四个只读 Worker 可并行；共享写入只经过 Writer/Coder；旧 attempt 不能覆盖新 attempt；冲突不能通过投票被静默消除。

### Phase 4：业务 Skill 接入

业务模块只实现 Skill、业务 schema、业务工具适配和业务图，不重新实现 retry/checkpoint/Langfuse。

---

## 13. Definition of Done

公共模板达到可被业务复用，至少满足：

- Reactive、Plan、Multi-Agent 三种模式有明确分流标准。
- 所有外部调用有 task/attempt/operation 身份和预算记录。
- 重试仅限于已分类的安全瞬时错误。
- 外部结果未知时进入对账/人工，不盲目重放。
- Plan、Recovery、Evidence、Completion 都可序列化并绑定版本。
- LangGraph checkpoint 使用持久化 saver，恢复入口与人工 interrupt 分开。
- Langfuse trace 可以串起 run、node、generation、tool、retry 和 completion。
- Langfuse 失效、业务 Artifact/Checkpoint 失效、外部请求未知三类错误有不同处理。
- Multi-Agent 不共享无边界上下文，不把并行当作 exactly-once。
- 业务文档只依赖公共契约，不复制公共实现。

---

## 14. 本文明确不承诺的内容

- 不承诺模型调用 exactly-once。
- 不承诺线程池 timeout 可以杀死已执行代码。
- 不承诺 Langfuse 的 trace 等于业务事实审计。
- 不承诺已有三个学习项目可以无改动直接拼成公共包。
- 不承诺所有 LangChain provider 都支持同样的原生 WebSearch。
- 不把当前静态源码审阅当作测试通过或生产可用证明。

---

## 15. 参考路径与官方文档

### 当前项目

- `advanced-coding-agent/src/advanced_coding_agent/planning/graph.py`
- `advanced-coding-agent/src/advanced_coding_agent/planning/execution.py`
- `advanced-coding-agent/src/advanced_coding_agent/planning/replan.py`
- `advanced-coding-agent/src/advanced_coding_agent/long_horizon/recovery.py`
- `advanced-coding-agent/src/advanced_coding_agent/long_horizon/completion.py`
- `advanced-coding-agent/src/advanced_coding_agent/multi_agent/decision.py`
- `advanced-coding-agent/src/advanced_coding_agent/multi_agent/execution.py`
- `advanced-coding-agent/src/advanced_coding_agent/multi_agent/aggregation.py`
- `support-agent/src/support_agent/persistence/checkpointer.py`
- `support-agent/src/support_agent/services/runner.py`
- `agent-mini/src/agent/runtime.py`
- `agent-mini/src/agent/loop.py`
- `agent-mini/src/agent/cost.py`
- `agent-mini/src/agent/checkpoint.py`

### 官方资料

- LangGraph Checkpoint：<https://docs.langchain.com/oss/python/langgraph/checkpointers>
- LangGraph Fault Tolerance：<https://docs.langchain.com/oss/python/langgraph/fault-tolerance>
- LangGraph Interrupts：<https://docs.langchain.com/oss/python/langgraph/interrupts>
- LangGraph Graph API：<https://docs.langchain.com/oss/python/langgraph/use-graph-api>
- LangGraph Subgraphs：<https://docs.langchain.com/oss/python/langgraph/use-subgraphs>
- LangChain Structured Output：<https://docs.langchain.com/oss/python/langchain/structured-output>
- Langfuse LangChain/LangGraph：<https://langfuse.com/integrations/frameworks/langchain>
- Langfuse Python v3→v4：<https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4>
- Langfuse Masking：<https://langfuse.com/docs/observability/features/masking>

---

## 最终结论

公共 Agent 模板的核心不是多写几个 Agent，而是把**执行模式、状态、错误恢复、持久化、可观测性和完成门禁**做成稳定边界。当前项目已经分别验证了这些能力的关键思想；下一步应该提取契约并新建独立模板模块，而不是继续扩大任意一个已有 Demo 的职责。
