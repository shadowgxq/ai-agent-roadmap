# Session 04｜用 LangGraph 重写 Routing Workflow

## 1. 本 Session 的明确学习目标

这次不是为了“再写一个能调用模型的程序”，而是要学会把已经理解的手写工作流，映射成 LangGraph 的图结构。

完成本 Session 后，你应该能够独立回答：

1. 哪些数据应该放进 LangGraph state，哪些依赖不应该放进去？
2. 普通节点、条件边和 `START` / `END` 分别承担什么责任？
3. 模型负责做路由判断后，为什么仍然要由 Python 限制合法分支？
4. 手写的 `ROUTE_HANDLERS[route]` 与 LangGraph 的 `add_conditional_edges` 是什么关系？
5. 框架替我们管理了什么，又有哪些业务规则仍然必须自己实现？

## 2. 执行前核心方案

### 2.1 要解决的问题

输入一个开发任务，先把它分类到以下四种意图之一，然后只执行对应分支：

- `code_generation`：根据需求生成新代码；
- `code_review`：只评审已有代码；
- `bug_fix`：定位并修复已有问题；
- `explanation`：解释代码或技术概念。

本 Session 只重写 W5 的 routing workflow，不同时引入循环、持久化、人工审批或前端事件。

### 2.2 核心执行链

```text
用户任务
  ↓
classify_route
  ├─ 模型返回 RouteDecision
  └─ state 写入 route / route_reason / status
  ↓
select_route 条件边
  ├─ code_generation → 生成代码
  ├─ code_review     → 评审代码
  ├─ bug_fix         → 修复代码
  └─ explanation     → 解释问题
  ↓
finalize
  ↓
END
```

每次运行只会进入一个业务分支。路由模型不能动态创造节点，也不能决定运行任意函数；它只能返回 `RouteName` 允许的四个值之一。

### 2.3 数据与责任边界

`RoutingState` 只保存恢复和理解工作流所需的业务数据：

| 字段 | 写入者 | 作用 |
|---|---|---|
| `task` | CLI / 调用方 | 原始任务 |
| `status` | 各节点 | 当前业务阶段 |
| `route` | `classify_route` | 选中的合法路线 |
| `route_reason` | `classify_route` | 路由理由 |
| `code` | 生成或修复分支 | 代码结果 |
| `summary` | 评审或解释分支 | 文本结果 |

模型客户端不放进 state，而是由 `create_routing_graph(model)` 通过闭包注入。原因是客户端属于运行依赖，不是业务状态，也不适合被 checkpoint 序列化。

### 2.4 实现顺序

1. 使用 `Literal` 定义合法路线和状态值。
2. 使用 Pydantic `RouteDecision` 约束模型的结构化路由结果。
3. 使用 `TypedDict` 定义图中节点共享的 `RoutingState`。
4. 实现 `classify_route`，只做分类，不执行具体业务。
5. 实现四个职责单一的业务节点。
6. 使用 `add_conditional_edges` 把路由结果映射到固定节点。
7. 所有分支汇合到 `finalize`，最后进入 `END`。
8. 增加独立 CLI，从命令行传入任务并输出最终 state。

### 2.5 执行前验收标准

- 图可以被编译成 `CompiledStateGraph`。
- 图中存在一个分类节点、四个业务节点和一个收尾节点。
- 每次路由只能命中一个预先注册的分支。
- 每个节点只返回自己修改的 state 字段。
- 与手写版使用相同的四种 route 名称和业务提示词。
- 真实模型对照需要单独获得允许，因为会消耗 token。

## 3. 手写版与框架版的对应关系

| 手写 `agent-mini` | LangGraph `support-agent` | 含义 |
|---|---|---|
| `RoutingState(WorkflowState)` | `RoutingState(TypedDict)` | 工作流共享业务状态 |
| `RouteDecision.model_validate_json()` | `model.with_structured_output(RouteDecision)` | 校验模型的路由结果 |
| `router()` | `classify_route` 节点 | 判断任务路线 |
| `ROUTE_HANDLERS` 字典 | 条件边映射表 | 将 route 映射到固定处理器 |
| `await handler(runtime, state)` | LangGraph 调度选中的节点 | 执行唯一业务分支 |
| `state.status = ...` | 节点返回部分 state 更新 | 记录业务阶段 |
| `try / except` 控制整体流程 | 图 runtime 控制节点调度 | 框架接管流程编排 |

最关键的变化不是代码变短，而是控制流从一个普通 Python 函数内部，变成了可以被框架识别、检查和扩展的图。

## 4. 核心代码导读

### 4.1 为什么 state 用 `TypedDict`

```python
class RoutingState(TypedDict):
    task: str
    status: RoutingStatus
    route: NotRequired[RouteName]
    route_reason: NotRequired[str]
    code: NotRequired[str]
    summary: NotRequired[str]
```

`task` 和 `status` 是初始运行就必须提供的字段。其余字段由后续节点按执行路线逐步产生，所以使用 `NotRequired`。

这里的 state 是节点之间的共享数据契约，不是对象依赖容器。每个节点接收当前 state，并返回本节点产生的部分更新。

### 4.2 为什么路由输出用 Pydantic

```python
class RouteDecision(BaseModel):
    route: RouteName
    reason: str = Field(min_length=1)
```

路由结果来自模型，属于不可信外部输出。Pydantic 负责确保：

- `route` 必须是四个合法值之一；
- `reason` 不能为空；
- 非法结构不能直接进入条件边。

这说明“模型做判断”不等于“模型拥有控制权”。控制流边界仍由代码定义。

### 4.3 条件边如何替代 handler 字典

```python
builder.add_conditional_edges(
    "classify_route",
    select_route,
    {
        "code_generation": "code_generation",
        "code_review": "code_review",
        "bug_fix": "bug_fix",
        "explanation": "explanation",
    },
)
```

`select_route` 读取 state 中已经校验过的 `route`。映射表决定下一步能进入哪个节点。

这与手写版 `ROUTE_HANDLERS[decision.route]` 的业务含义相同，但 LangGraph 能显式看到节点和边，为后续 streaming、checkpoint、重试和可视化提供结构基础。

### 4.4 为什么还需要 `finalize`

四个分支都汇合到 `finalize`，统一把状态改为 `completed`：

```text
任意业务分支 → finalize → END
```

如果以后需要统一记录完成事件、计算费用或清理临时资源，可以放在这个汇合节点，而不必复制到四个业务节点。

## 5. 本 Session 的收益

### 5.1 学习收益

- 真正理解了 LangGraph 的核心不是“调用模型”，而是管理状态和控制流。
- 学会区分结构化模型输出与图状态：前者负责校验一次模型决定，后者负责节点间传递业务数据。
- 学会把模型决策限制在代码声明的安全边界内。
- 建立了从手写工作流迁移到框架工作流的一对一思考方式，而不是死记 API。

### 5.2 工程收益

- 路由节点、业务节点、状态契约和模型依赖的职责更清楚。
- 分支结构可以被 LangGraph runtime 识别，后续容易增加事件流、checkpoint 和人工审批。
- 每个节点只返回局部更新，减少共享对象被随意修改的问题。
- 新增路线时，可以明确看到需要补充的类型、节点和条件边映射。

### 5.3 框架没有替我们解决的事情

- 路由分类标准是否合理；
- 提示词和模型输出质量；
- API 失败、超时和重试策略；
- token 成本上限；
- 业务结果是否正确；
- 哪些 state 值应该持久化。

LangGraph提供调度能力，但不会替业务做这些设计决定。

## 6. 当前完成与验证状态

已经完成：

- 类型化 `RouteDecision` 与 `RoutingState`；
- 分类节点、四个业务节点、条件边和收尾节点；
- `support-routing` CLI 入口；
- 非联网静态构图，结果为 `CompiledStateGraph`。

尚未完成：

- 没有调用 DeepSeek 运行固定输入；
- 没有比较手写版与框架版的输出和模型调用次数；
- 没有记录已知失败输入；
- 没有完成 W13 Session 04 的真实模型业务等价验收。

因此当前结论只能是“图结构实现完成”，不能说“真实业务运行已经通过”。

## 7. 用户批准后可执行的真实对照

框架版命令：

```bash
cd /home/gxq/ai-agent-roadmap/support-agent
uv run support-routing "解释 Python 的 yield"
```

建议至少对照以下固定输入：

| 输入 | 预期 route |
|---|---|
| `请写一个 Python 二分查找函数` | `code_generation` |
| `请评审下面这段 Python 代码` | `code_review` |
| `这个函数遇到空数组会报错，请修复` | `bug_fix` |
| `请解释 Python 的 yield` | `explanation` |

每个框架版输入通常包含一次路由模型调用和一次业务分支调用。执行前应明确真实模型调用会消耗 token，并由用户确认是否运行。

## 8. 学习自测

1. 为什么不能让模型直接返回一个任意 Python 函数名并执行？
2. `RouteDecision` 和 `RoutingState` 为什么不合并成一个模型？
3. 如果删除 `finalize`，当前业务结果会发生什么变化？未来扩展又会损失什么？
4. 为什么模型客户端通过 graph factory 注入，而不是保存在 state？
5. 新增 `test_generation` 路线时，至少需要修改哪些位置？

能不用看代码讲清以上问题，才算真正掌握本 Session 的核心知识。

## 9. 后续 Session 的固定学习节奏

后面的每个 Session 都按以下顺序推进：

1. 先给出明确学习目标。
2. 给出核心方案、数据流、实现范围、收益和验收标准。
3. 停下来让用户阅读和确认。
4. 用户明确回复“执行”后再修改代码。
5. 实现后说明代码映射、实际验证和未验证边界。
6. 最后用自测题确认是否掌握，而不只确认代码是否跑通。
