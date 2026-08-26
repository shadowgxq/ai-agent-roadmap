# Session 06｜Agent SDK 横向对照与技术选型

## 1. 本 Session 的定位

前 5 个 Session 让我们完成了一个最小的 `support-agent`：使用 LangChain 处理模型、工具和结构化输出，再使用 LangGraph 表达路由、状态和节点调度。

本 Session 不再创建第三份 Agent，也不把当前项目迁移到另一个 SDK。目标是回答一个更重要的工程问题：

> 面对一个新的 Agent 项目，应该根据什么业务前提选择手写 runtime、LangGraph、OpenAI Agents SDK 或 Claude Agent SDK？

这是一节架构阅读和选型课，不是一节 API 堆砌课。

## 2. 明确学习目标

完成本 Session 后，你应该能够：

1. 解释四种方案在 Agent loop、tool、handoff/subagent、guardrail、state 和 trace 上的差异。
2. 说清“SDK 帮我们管理什么”和“业务代码仍然必须决定什么”。
3. 判断什么时候应该使用显式图，什么时候应该使用 SDK 提供的 Agent Runner。
4. 解释为什么当前 `support-agent` 不需要再实现一份 OpenAI 或 Claude 版本。
5. 用具体业务前提给出框架选择，而不是使用“更简单”“更方便”这类空泛理由。

## 3. 本 Session 的核心方案

### 3.1 对照对象

| 方案 | 本项目中的参照物 | 核心问题 |
|---|---|---|
| 手写 runtime | `agent-mini` | 我要不要自己掌控每一轮、每个工具和每个安全边界？ |
| LangGraph | `support-agent` 当前实现 | 我的业务流程是否需要显式状态图、分支、恢复和人工介入？ |
| OpenAI Agents SDK | 官方 `Agent` + `Runner` | 我是否优先使用 OpenAI 生态的 Agent 编排能力？ |
| Claude Agent SDK | Claude 原生本地 Agent SDK | 我是否需要 Claude 原生的工具、MCP 和 coding-agent 运行方式？ |

### 3.2 学习路径

```text
agent-mini 的手写 loop
        ↓
support-agent 的 LangGraph workflow
        ↓
OpenAI Agents SDK / Claude Agent SDK 的高层抽象
        ↓
根据业务约束做选型，而不是根据 API 数量做选型
```

### 3.3 本 Session 的实现范围

只新增本教程和一份选型结论，不修改运行代码：

```text
support-agent/tutorials/session-06-sdk-comparison.md
```

不做以下工作：

- 不安装 `openai-agents` 或 `claude-agent-sdk`；
- 不创建第二个或第三个 support agent；
- 不更换当前 DeepSeek 配置；
- 不调用真实模型；
- 不做性能、价格或 token benchmark；
- 不把不同 SDK 的宣传能力当成当前项目已经验证的能力。

## 4. 四种方案的核心抽象

### 4.1 手写 runtime：控制流完全由业务代码掌握

`agent-mini` 自己负责：

```text
读取 state
  → 调用模型
  → 解析 tool call
  → 执行工具
  → 写回消息和 state
  → 判断是否继续
```

它的优势是边界透明：最大轮次、工具权限、成本、上下文压缩、异常处理和事件协议都能直接写在代码里。

代价是每一个通用能力都需要自己维护，容易出现 loop、重试、状态和日志逻辑散落的问题。

### 4.2 LangGraph：把业务流程表达成显式图

当前 `support-agent` 的主抽象是：

```text
TypedDict state
  + node
  + conditional edge
  + START / END
  + graph runtime
```

LangGraph 适合这样的流程：状态边界明确、节点职责明确、分支和循环值得被审计，并且后续可能需要 checkpoint、streaming、人工审批或恢复执行。

它不会替业务决定：路由规则是什么、何时重试、哪些工具有副作用、什么结果算成功，以及哪些状态应该持久化。

### 4.3 OpenAI Agents SDK：以 Agent Runner 为中心的高层编排

OpenAI 官方 Quickstart 的学习路径是定义一个 Agent，再使用 Runner 运行；随着流程变复杂，可以继续增加工具和 specialist agents。[OpenAI Agents SDK Quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart)

概念链可以记成：

```text
Agent 定义
  → Runner 执行
  → function / hosted / MCP tools
  → specialist agent / handoff
  → guardrail / human review
  → result / tracing
```

它更像一个已经准备好的 Agent harness：开发者声明 Agent 的身份、提示词、模型和工具，然后由 Runner 处理一次运行中的模型与工具协作。

这里的“高层”不代表没有控制能力，而是控制点集中在 SDK 约定的 Agent、tool、handoff、guardrail、result 和 tracing 接口中。

### 4.4 Claude Agent SDK：Claude 原生的 Agent 运行面

Claude Agent SDK 的关键学习点不是“它也有一个 Agent 类”，而是它把 Claude 原生的工具和 coding-agent 工作方式组织成一个可运行的 Agent 会话。官方迁移文档展示了 `ClaudeAgentOptions`、`ClaudeSDKClient`、SDK MCP server 和工具装饰器等本地运行概念。[Claude Agent SDK migration](https://platform.claude.com/docs/en/managed-agents/migration)

需要特别区分两个概念：

- Claude Agent SDK：Agent loop 和工具通常运行在开发者管理的进程中；
- Claude Managed Agents：Agent 配置和 session 由 Anthropic 托管，使用持久化 session、事件流和托管工具环境。

本 Session 只把前者作为 SDK 对照对象，并把后者作为当前官方产品边界记录下来，不把两者写成同一个 SDK。

## 5. 六个关键维度对照

### 5.1 Agent loop

| 方案 | loop 的主要所有者 | 学习重点 |
|---|---|---|
| 手写 runtime | 业务代码 | 每一轮何时结束，完全自己决定 |
| LangGraph | Graph runtime + 业务边 | loop 是图中的边和条件，循环边必须有硬上限 |
| OpenAI Agents SDK | Runner | SDK 负责 Agent 运行，业务通过工具、handoff 和 guardrail 影响流程 |
| Claude Agent SDK | Claude SDK session / query | SDK 处理 Claude 原生 Agent 会话和工具协作 |

选择问题不是“谁的 loop 最先进”，而是“我是否需要直接掌握每一轮的控制流”。

### 5.2 Tool

工具至少有三层责任：声明输入输出、决定何时调用、执行副作用。

| 方案 | schema / 声明 | 执行责任 |
|---|---|---|
| 手写 runtime | Pydantic / JSON schema / 自定义 registry | 业务代码解析和执行 |
| LangGraph | `@tool` 或节点输入契约 | tool 或节点执行，图负责编排 |
| OpenAI Agents SDK | function tools、hosted tools、MCP 等 SDK 接口 | 依工具类型由 SDK、平台或应用执行 |
| Claude Agent SDK | Claude tools、MCP、应用自定义工具 | 本地 Agent SDK 或应用按工具边界执行 |

工具描述必须明确副作用、权限、错误和返回结构。任何 SDK 都不能因为工具声明合法，就自动保证业务操作安全。

### 5.3 Handoff / subagent

| 方案 | 典型表达 | 适合的边界 |
|---|---|---|
| 手写 runtime | 自己调用另一个 agent 函数 | 需要完全控制上下文、权限和结果合并 |
| LangGraph | subgraph 或受限 agent node | 子流程拥有明确 state 和生命周期 |
| OpenAI Agents SDK | specialist agent 与 handoff | 多个角色之间的责任移交 |
| Claude Agent SDK | Agent 配置、MCP 或会话级协作 | Claude 原生工具与会话边界 |

“多 Agent”不是默认收益。只有当角色拥有不同工具、权限、提示词或生命周期时，拆分才值得付出上下文和观测成本。

### 5.4 Guardrail / human review

安全控制可以发生在三个时间点：输入前、模型输出后、工具执行前。

| 时间点 | 应该检查什么 |
|---|---|
| 输入前 | 用户是否有权发起任务，输入是否越过业务范围 |
| 输出后 | 结构是否正确，内容是否满足业务政策 |
| 工具执行前 | 是否有副作用，是否需要人工确认，参数是否允许 |

OpenAI Agents SDK 官方文档把 guardrails 和 human review 作为 Agent workflow 的独立能力介绍，而不是把它们隐藏成普通 prompt。[OpenAI guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)

在当前 `support-agent` 中，`lookup_ticket_policy` 是只读工具，真正的退款、账户变更和人工升级仍然应该在明确的业务边界中实现，不能只依赖模型自觉。

### 5.5 State / session

| 概念 | 说明 |
|---|---|
| graph state | 节点之间传递的业务状态 |
| run result | 一次 Agent 执行返回的结果和运行信息 |
| conversation/session | 跨轮次保留的对话或执行上下文 |
| checkpoint | 为恢复图执行保存的状态快照 |

它们不是同一个东西。把 SDK 的 session 直接当成业务数据库，或者把所有对话内容都塞进 graph state，都会造成边界混乱。

### 5.6 Trace / observability

需要观察的不只是最终答案，还包括：

- 哪个 Agent 或节点被执行；
- 调用了什么工具；
- 工具参数和结果是否合规；
- 发生了多少轮和多少次重试；
- 延迟、token、费用和失败原因；
- 最终输出是否满足业务契约。

OpenAI 官方 Agents 文档把 integrations and observability 单独列为 Agent 能力；当前项目的 LangGraph trace 则是本地节点更新，二者都说明“过程证据”不能由最终文本替代。[OpenAI integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)

## 6. 与当前项目的逐项映射

| 当前项目 | 手写版 | LangGraph 版 | SDK 对照问题 |
|---|---|---|---|
| 模型调用 | `WorkflowRuntime.complete` | `model.invoke` | SDK 是否接管调用和重试？ |
| 路由 | `router` + `ROUTE_HANDLERS` | `classify_route` + 条件边 | 路由由模型决定，还是由图声明？ |
| 工具 | registry + Pydantic schema | `@tool` | 工具 schema 和执行权限在哪里？ |
| 状态 | `WorkflowState` | `RoutingState` | 状态是否可恢复、可序列化、可审计？ |
| 结束条件 | `run_routing` / loop 逻辑 | `finalize` → `END` | Runner 或 session 的结束条件是什么？ |
| 观测 | 自定义 workflow 日志 | `graph.stream(..., "updates")` | SDK trace 能否覆盖业务所需证据？ |
| 错误处理 | 手写异常和重试 | 当前图由 runtime 抛出，未自定义重试 | 失败是否可恢复，是否会重复副作用？ |

## 7. 选型决策表

### 7.1 优先选择手写 runtime

当以下条件成立时，保留手写 runtime 有价值：

- 需要学习和证明底层 loop 原理；
- 工具执行权限和副作用控制必须逐行可见；
- 业务需要非常规的上下文压缩、成本闸门或重试策略；
- Agent 仍处于探索期，流程结构尚未稳定。

这正是 `agent-mini` 的定位。它不是“落后版本”，而是底层控制和实验基线。

### 7.2 优先选择 LangGraph

当以下条件成立时，LangGraph 更匹配：

- 业务流程可以拆成稳定节点和边；
- state 需要被恢复、审计或跨节点传递；
- 存在条件分支、有限循环、人工审批或长任务；
- 团队希望保留模型 provider 的替换空间；
- 需要把过程事件适配成自己的应用协议。

当前 `support-agent` 选择 LangGraph，是因为工单路由、政策查询、升级和回复天然是业务流程边界，而不是因为 LangGraph 能自动产生更好的答案。

### 7.3 优先选择 OpenAI Agents SDK

当以下条件成立时，可以优先评估 OpenAI Agents SDK：

- 项目主要使用 OpenAI 的模型和工具生态；
- 希望快速获得 Agent Runner、tool orchestration、handoff、guardrail 和 tracing 的统一接口；
- 多个 specialist agent 的职责和移交关系比显式业务状态图更重要；
- 团队愿意接受 SDK 约定的运行和观测模型。

它适合快速组装以 Agent 为中心的应用，但不能替业务决定审批、权限、数据一致性和副作用边界。

### 7.4 优先选择 Claude Agent SDK

当以下条件成立时，可以评估 Claude Agent SDK：

- 项目明确围绕 Claude 原生能力和 coding-agent 工作方式建设；
- 需要 Claude 原生工具、MCP 或本地进程中的 Agent 会话；
- 团队希望使用 Claude SDK 对 loop、工具和会话提供的约定；
- 运行环境、权限模型和供应商绑定是可接受的前提。

如果真正需要 Anthropic 托管的持久化 Agent session，则要单独评估 Managed Agents，而不是把它当作本地 Claude Agent SDK 的一个小配置项。

## 8. 为什么当前 `support-agent` 不实现第二份版本

同时维护 LangGraph、OpenAI Agents SDK 和 Claude Agent SDK 三份实现，会引入三个问题：

1. 不能判断差异来自业务逻辑还是框架行为。
2. 每份实现都需要单独维护配置、错误、trace 和验收。
3. 学习重点会从“理解抽象边界”退化为“复制三遍 API”。

当前最合理的做法是：

```text
agent-mini       = 手写机制基线
support-agent    = LangGraph 业务实现
Session 06       = SDK 能力与选型对照
```

如果未来真的要迁移，应该先定义共享业务契约和固定评测集，再选择一个明确的目标 SDK，而不是在学习阶段平行维护多个运行版本。

## 9. 本 Session 的收益

### 学习收益

- 从“会用一个框架”提升到“能解释多个 Agent 抽象层”；
- 学会区分 Agent、workflow、session、state、checkpoint 和 trace；
- 理解 handoff/subagent 是责任边界，不是简单多调用一次模型；
- 理解 guardrail 必须和工具副作用、人工审批结合；
- 建立以业务约束为中心的技术选型方法。

### 工程收益

- 避免为了追逐 SDK 而重复实现同一个项目；
- 能在项目评审中解释框架选择的理由和代价；
- 能识别 SDK 接管 loop 后仍需自行负责的权限、成本和数据一致性问题；
- 为将来迁移或替换 Agent runtime 预留清晰的业务契约。

## 10. 验收标准

本 Session 不以“安装了几个 SDK”作为完成标准，而以以下结果作为完成标准：

- [ ] 有一张手写 runtime / LangGraph / OpenAI Agents SDK / Claude Agent SDK 对照表；
- [ ] 能说清 loop、tool、handoff、guardrail、state、trace 六个维度；
- [ ] 能解释当前 `support-agent` 继续选择 LangGraph 的业务原因；
- [ ] 能给出 OpenAI Agents SDK 和 Claude Agent SDK 的适用前提；
- [ ] 能说明为什么不创建第三份实现；
- [ ] 不把未运行、未测量的 SDK 能力写成当前项目事实。

## 11. 自测题

1. `support-agent` 当前的 `RoutingState` 为什么不是 OpenAI Agents SDK 的 run result？
2. 如果模型返回了合法但错误的 route，哪一层能发现，哪一层发现不了？
3. 什么时候一个 handoff 应该改成 LangGraph 的显式节点？
4. 工具返回成功，为什么不代表业务操作可以提交？
5. 为什么 Claude Agent SDK 和 Claude Managed Agents 不能直接当作同一个方案？
6. 如果项目必须支持 OpenAI 和 Claude 两种 provider，应该先抽象什么，不能先复制什么？

## 12. 本 Session 的验证边界

已完成：

- 阅读并整理 OpenAI Agents SDK 官方 Quickstart、编排、guardrail 和 observability 资料；
- 阅读并整理 Anthropic 官方 Claude Agent SDK / Managed Agents 边界资料；
- 结合 `agent-mini` 和 `support-agent` 当前代码建立映射表；
- 编写本对照教程。

未执行：

- 未安装或运行 OpenAI Agents SDK；
- 未安装或运行 Claude Agent SDK；
- 未发起任何真实模型调用；
- 未进行 latency、token、费用或质量 benchmark；
- 未声称不同 SDK 在本项目中已经达到业务等价。

## 13. 资料入口

- [OpenAI Agents SDK Quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart)
- [OpenAI Agents SDK orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
- [OpenAI guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- [OpenAI integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)
- [Claude Agent SDK migration](https://platform.claude.com/docs/en/managed-agents/migration)
- [Claude SDK tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)
