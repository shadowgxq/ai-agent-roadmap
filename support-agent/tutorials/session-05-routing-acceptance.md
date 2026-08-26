# Session 05｜Routing Workflow 对照、反思与小型验收

## 1. 本 Session 的明确学习目标

本 Session 要把 Session 04 的“图结构已经编译”推进到“知道它在固定输入下如何运行，并能解释它为什么这样设计”。

完成后，你应该能够：

1. 用 5 分钟讲清手写 routing workflow 和 LangGraph routing workflow 的控制流。
2. 说清 `TypedDict` state、Pydantic structured output、节点和条件边各自负责什么。
3. 通过 trace 判断一次运行实际经过了哪些节点，而不是只看最终文本。
4. 区分类型校验能够发现的错误，以及模型语义判断错误。
5. 说明客服工单 Agent 为什么适合稳定的图工作流，而 coding agent 仍可能保留手写 loop。

## 2. 本 Session 的核心方案

### 2.1 验收对象

验收对象是 Session 04 创建的 `support-routing`：

```text
classify_route
  → 一个固定业务分支
  → finalize
  → END
```

本 Session 增加 `--trace`，将每个节点产生的 state 增量输出到 stderr，最终结果仍然输出为 stdout JSON。

这样可以同时满足两件事：

- 人阅读时能看到图的执行过程；
- 脚本仍可以单独解析最终 JSON。

### 2.2 固定验收输入

| 编号 | 输入意图 | 预期 route |
|---|---|---|
| R1 | 生成二分查找代码 | `code_generation` |
| R2 | 评审 `add` 函数 | `code_review` |
| R3 | 修复 `add` 函数 | `bug_fix` |
| R4 | 解释 `yield` 和 `return` | `explanation` |
| R5 | 同时要求修复并解释 | `bug_fix`，以最终交付目标为准 |

成功运行时，每个输入应经过一次路由调用和一次业务分支调用。图 trace 应当包含：

```text
classify_route → selected branch → finalize
```

## 3. 为什么要看 trace

只看最终答案，无法确认模型是否真的经过了预期路线。例如，用户要求“修复代码并解释原因”，最终文字可能看起来合理，但我们仍然需要知道它进入的是 `bug_fix` 还是 `explanation`。

trace 提供了比最终答案更接近控制流的证据：

```json
[trace] {"node": "classify_route", "updates": {"route": "bug_fix"}}
[trace] {"node": "bug_fix", "updates": {"code": "..."}}
[trace] {"node": "finalize", "updates": {"status": "completed"}}
```

这里的 `updates` 是节点对共享 state 的局部修改，不是完整 state 快照。

## 4. 实际执行结果（2026-08-26）

### 4.1 结果总表

| 输入 | 实际 route | 最终状态 | 结果 |
|---|---|---|---|
| R1 二分查找 | `code_generation` | `completed` | 通过 |
| R2 代码评审 | `code_review` | `completed` | 通过 |
| R3 修复函数 | `bug_fix` | `completed` | 通过 |
| R4 yield 解释 | `explanation` | `completed` | 通过 |
| R5 修复并解释 | `bug_fix` | `completed` | 通过 |

### 4.2 Trace 证据

R4 的实际 trace：

```text
classify_route → explanation → finalize
```

R5 的实际 trace：

```text
classify_route → bug_fix → finalize
```

R5 说明当前路由提示词的规则生效：当任务同时要求修复和解释时，选择最终交付目标更接近的 `bug_fix`。不过业务分支的提示词仍可能同时返回解释文字，因此“路由正确”和“分支输出严格遵守格式”是两个不同的验收问题。

### 4.3 失败 trace 记录

本轮 5 个真实输入均成功，没有自然产生失败 trace。这里不人为伪造失败，也不把之前的 401 API key 错误或 DeepSeek thinking/tool-choice 错误冒充本 Session 的失败。

因此本轮可以确认：

- 成功路径已被真实模型验证；
- 本轮没有覆盖运行时失败路径；
- 结构化输出失败、网络异常和业务分支失败仍需要后续用受控测试替代真实 API 失败来验证。

## 5. 手写版与框架版的对照

| 对比项 | `agent-mini` 手写版 | `support-agent` LangGraph 版 |
|---|---|---|
| 路由结果 | 模型返回 JSON，手动 `model_validate_json` | `with_structured_output(RouteDecision)` |
| 非法路由 | Pydantic 校验后抛错 | `RouteName` 和条件边映射限制合法分支 |
| 路由分发 | `ROUTE_HANDLERS[route]` | `add_conditional_edges` |
| 状态更新 | handler 直接修改 Pydantic state | 节点返回局部 state 更新 |
| 流程收尾 | `run_routing` 统一设置 `completed` | `finalize` 节点汇合到 `END` |
| 正常模型调用数 | 1 次 router + 1 次 handler | 1 次 classify + 1 次 branch |
| 解析失败处理 | 显式循环重试 2 次 | 交给 structured-output/provider 路径处理，当前图未自定义重试 |
| 执行过程 | 需要自己加日志 | 可以从图的节点更新中观察 |

两者在本组输入上的业务路由结果等价：都只选择一个 route，再执行对应 handler。它们的工程表达不同：手写版把调度过程写在 Python 控制流里，框架版把调度过程声明为图。

## 6. 框架收益与新增失败模式

### 6.1 实际收益

- 节点、边和汇合点成为显式结构，控制流更容易阅读和扩展。
- state 更新边界清楚，节点不需要共享可变对象。
- trace 不需要在每个 handler 中复制一套流程日志。
- 后续接入 streaming、checkpoint、人工审批时，有明确的图节点可以挂载。

### 6.2 新的失败模式

- structured output 解析失败，导致无法进入条件边；
- provider 不支持当前 structured-output 方法或 tool choice；
- 模型把任务语义判断错，但返回的结构仍然合法；
- 业务分支模型调用失败，导致 `finalize` 不会执行；
- 节点状态字段设计不完整，导致后续节点缺少输入。

其中“返回合法结构”不代表“业务判断正确”。例如模型返回 `explanation` 是合法的，但对一个明确的修复任务做错了路由，Pydantic 并不能发现。

## 7. 为什么客服工单适合 LangGraph

客服工单通常有相对稳定的状态和流程边界：分类、查询政策、人工升级、生成回复、结束。企业往往还需要持久化、审计、事件流和人工介入，这些都适合表达为显式图。

coding agent 的工具调用路径更开放：它可能读取文件、执行命令、修改代码、运行检查，再根据结果决定下一步。此时手写 loop 能让开发者直接控制最大轮次、工具权限、成本和终止条件。

这不是“框架一定优于手写”的结论，而是边界选择：

- 稳定、可审计、节点边界清楚的业务流程，优先考虑 LangGraph；
- 探索性强、工具路径动态、底层安全控制要求高的 agent loop，可以保留手写 runtime。

## 8. 可执行命令

在 WSL 中运行单条带 trace 的验收：

```bash
cd /home/gxq/ai-agent-roadmap/support-agent
uv run support-routing --trace "请解释 Python 中 yield 和 return 的区别，回答简洁一些"
```

只看最终 JSON：

```bash
uv run support-routing "这个函数写错了，请修复并只输出修复后的代码：def add(a, b): return a - b"
```

当前每次成功执行包含两次模型调用；真实运行会消耗 token。

## 9. 本 Session 的验证边界

已执行：

- `uv run support-routing --help`，确认 `--trace` 入口可用；
- 5 条真实 DeepSeek 固定输入；
- 5 条输入的实际 route 和最终状态检查；
- trace 节点顺序检查；
- `git diff --check`。

未执行：

- pytest 测试套件；
- 手写版和框架版的并行真实模型跑分；
- 受控结构化输出失败测试；
- 网络超时、provider 错误和业务节点异常测试；
- token 用量统计对比。

所以本 Session 的结论是：5 条固定输入的框架版成功路径通过，路由与图控制流符合预期；失败路径和精确成本对比仍未验收。

## 10. 学习自测

1. 为什么 R5 选择 `bug_fix`，但最终输出仍可能包含解释文字？
2. 如果模型返回了一个不存在的 route，哪一层应该阻止它进入业务节点？
3. 为什么 `finalize` 比在四个业务节点里分别设置 `completed` 更容易扩展？
4. LangGraph 在本 Session 中减少了哪类代码，增加了哪类失败模式？
5. 如果你要给这个工单 Agent 增加人工审批，应该把审批放在哪个节点边界？

能够结合本次真实 trace 回答这些问题，才算完成本 Session，而不是只记住 `add_conditional_edges` 的 API 名称。
