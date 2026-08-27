# W14 Session 1｜冻结 TicketAgentState 与 Graph 契约

## 1. 本 Session 的位置

W13 解决的是 LangChain / LangGraph primitive 与手写 Agent 的映射问题。W14 开始进入企业业务编排：同一条工单流程里，哪些步骤必须由代码控制，哪些步骤适合交给 LLM，以及这些步骤之间如何通过稳定 state 连接起来。

本 Session 不追求让完整工单 Agent 立即回答用户，而是先把后续所有 Session 都要依赖的业务契约冻结下来。

核心原则是：

> 先定义业务状态和节点边界，再实现节点；不要让 state 在开发过程中变成什么都往里塞的变量篮子。

## 2. 明确学习目标

完成本 Session 后，你应该能够：

1. 说清 `TicketAgentState` 保存什么、不保存什么。
2. 区分 graph state、Pydantic 模型和运行时模型客户端。
3. 为每个 node 写出明确的输入字段、输出字段、错误码和模型调用标记。
4. 判断一个步骤应该使用 Python 还是 LLM。
5. 在不调用模型的情况下，使用手造 state 走通确定性路径。

## 3. W14 最终业务图

W14 的完整目标流程是：

```text
START
  ↓
normalize_ticket                 # 确定性代码
  ↓
classify_ticket                  # LLM structured output
  ↓
是否需要补充信息？
  ├─ 是 → build_clarification → finalize → END
  └─ 否 → response_subgraph
              ├─ retrieve_policy_stub
              ├─ draft_response
              └─ assess_risk
                         ↓
                      finalize → END
```

本 Session 只冻结这张图和它的契约。`response_subgraph` 内部的政策检索、回复生成和风险评估会在后续 Session 分阶段实现；当前未实现的路径会显式返回 `RESPONSE_SUBGRAPH_NOT_READY`，不会伪装成成功结果。

## 4. 为什么先设计 State

如果先写 node，通常会出现这样的过程：

```text
先写 classify
  ↓
发现需要 missing_fields
  ↓
再给 state 加字段
  ↓
写 retrieve
  ↓
又把完整文档塞进 state
  ↓
最后没人说得清每个字段由谁负责
```

正确顺序是：

```text
业务流程
  ↓
状态字段
  ↓
节点读写表
  ↓
节点实现
  ↓
Graph 编排
```

LangGraph 官方将 graph 的核心拆成 State、Nodes 和 Edges：State 表示应用当前快照，Node 接收 state 并返回更新，Edge 决定下一步执行哪个 node。[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

## 5. TicketAgentState 的六类字段

### 5.1 标识字段

```text
organization_id
user_id
ticket_id
run_id
thread_id
```

它们用于定位企业、用户、工单和一次执行。`thread_id` 是为后续 checkpoint 和恢复准备的标识，本 Session 只保留字段，不实现持久化。

### 5.2 输入字段

```text
subject
description
customer_tier
```

这些是外部输入。normalize 节点可以清理它们，但不应该在后续节点中反复修改原始输入。

### 5.3 理解结果

```text
normalized_text
category
priority
missing_fields
```

这些字段描述模型或规则对工单的理解：标准化文本、业务类别、优先级和继续处理所需但当前缺失的信息。

### 5.4 证据字段

```text
evidence_refs
```

只保存小型引用对象，不保存完整政策文档：

```python
EvidenceRef(
    source_id="billing_refund_001",
    title="退款政策",
    snippet="符合条件的订单可以申请退款。",
)
```

这样 state 保持可序列化、可观察，后续回复节点也能明确知道使用了哪些证据。

### 5.5 输出字段

```text
draft_response
risk_level
risk_reasons
requires_approval
```

W14 只判断风险并输出 `requires_approval=True`，不真正暂停，也不执行退款、账户修改或删除操作。真正的人工审批和副作用执行属于 W15。

### 5.6 控制字段

```text
status
error_code
error_message
```

稳定错误码比只保留一个异常字符串更适合日志、SSE 和后续 API：

```text
INVALID_TICKET
MISSING_CLASSIFICATION
RESPONSE_SUBGRAPH_NOT_READY
```

## 6. State、模型和依赖的边界

### 6.1 Graph state

`TicketAgentState` 使用 `TypedDict`，用于节点之间传递业务数据。字段可以随着图的执行逐步产生，节点只返回它修改的字段。

### 6.2 Pydantic structured output

本 Session 定义三个 Pydantic 模型：

- `TicketWorkflowClassification`：一次分类模型的结构化结果；
- `EvidenceRef`：一条小型证据引用；
- `RiskAssessment`：一次风险判断结果。

W13 已经有一个同名语义的 `TicketClassification`，但它的类别和优先级枚举不同。为了不破坏 W13 的 `support-agent` CLI，本项目保留 W13 模型，并将 W14 版本命名为 `TicketWorkflowClassification`。

这不是重复设计，而是两个不同业务契约的兼容边界：

```text
W13 TicketClassification
  category: refund / billing / technical / account / other
  priority: low / medium / high / urgent

W14 TicketWorkflowClassification
  category: billing / account / product / technical / other
  priority: low / normal / high / urgent
```

### 6.3 运行依赖

模型 client 不放入 state。它由 `create_ticket_graph(model)` 注入到需要模型的节点闭包中，因为 client 是运行依赖，不是业务数据，也不应该被 checkpoint 序列化。

## 7. W14 模型契约

### 7.1 TicketWorkflowClassification

```python
class TicketWorkflowClassification(BaseModel):
    category: TicketCategory
    priority: TicketPriority
    needs_clarification: bool
    missing_fields: list[TicketMissingField]
    reason: str
```

模型可以判断语义，但只能返回代码声明的有限枚举。它不能返回一个任意节点名，也不能直接决定执行副作用。

### 7.2 EvidenceRef

```python
class EvidenceRef(BaseModel):
    source_id: str
    title: str
    snippet: str
```

证据对象是引用，不是原始文档的完整副本。后续 Session 3 会用固定 policy corpus 产生它。

### 7.3 RiskAssessment

```python
class RiskAssessment(BaseModel):
    risk_level: RiskLevel
    risk_reasons: list[str]
    requires_approval: bool
```

后续风险节点会先执行硬规则，再结合 LLM 语义判断，并取更高风险等级。

## 8. Node I/O Contract

实现前先固定这张表：

| Node | 读取 | 写入 | 调模型 | 当前状态 |
|---|---|---|---|---|
| `normalize_ticket` | `subject`, `description` | `normalized_text`, `status`, error fields | 否 | 已实现 |
| `classify_ticket` | `normalized_text` | `category`, `priority`, `missing_fields`, `status` | 是 | 已定义接口 |
| `build_clarification` | `missing_fields` | `draft_response`, `status` | 否 | 已实现 |
| `retrieve_policy_stub` | `category` | `evidence_refs`, `status` | 否 | 后续实现 |
| `draft_response` | `normalized_text`, `evidence_refs` | `draft_response`, `status` | 是 | 后续实现 |
| `assess_risk` | `normalized_text`, `draft_response` | risk fields, `status` | 是 + Code | 后续实现 |
| `finalize` | `status`, result fields | `status` | 否 | 已实现 |

这张表解决两个问题：

1. 每个节点的责任是否足够小；
2. 一个字段被多个节点修改时，是否真的有必要。

## 9. 确定性逻辑和 LLM 逻辑

### 应该使用 Python 的逻辑

```text
strip 空白
组合 normalized_text
判断字段是否为空
状态映射
固定问题模板
硬风险规则
最终状态组装
```

### 应该使用 LLM 的逻辑

```text
理解自然语言工单类别
判断优先级
识别不易穷举的缺失信息
根据证据生成自然语言回复
判断开放性的语义风险
```

规则很简单：能被代码稳定确定的事情，不要浪费一次模型调用；只有需要语义理解的事情才交给 LLM。

## 10. 离线契约 Demo

运行：

```bash
cd /home/gxq/ai-agent-roadmap/support-agent
uv run support-ticket-contract
```

这个命令不会读取 API key，也不会调用模型。它会：

1. 编译 W14 主图和 response subgraph；
2. 打印主图节点和边数量；
3. 打印全部 Node I/O Contract；
4. 使用手造的不完整工单执行 `normalize_ticket`；
5. 注入一份手造分类结果；
6. 执行确定性的澄清问题生成；
7. 执行 `finalize`。

核心结果：

```text
graph_nodes:
  normalize_ticket
  classify_ticket
  build_clarification
  response_subgraph
  finalize

deterministic_demo.status: completed
deterministic_demo.draft_response:
  请提供需要处理的订单号。
  请说明申请退款的原因。
```

这证明了状态契约和确定性澄清路径可以脱离模型运行，但不代表 W14 完整工单流程已经完成。

## 11. 当前实现与未实现边界

### 已完成

- W14 `TicketAgentState`；
- W14 分类、证据和风险 Pydantic 模型；
- W13 / W14 分类模型的兼容命名；
- 节点读写契约；
- 主图和 response subgraph 的结构骨架；
- 标准化、澄清和收尾确定性节点；
- 离线契约 CLI。

### 尚未完成

- 真实 `classify_ticket` 模型调用；
- 固定 policy corpus；
- 回复草稿生成；
- 硬风险规则与语义风险合并；
- 应用事件适配层；
- 12 个 fixture；
- `interrupt()` 和人工审批。

## 12. 验证记录

已执行：

- `uv run support-ticket-contract`；
- 图静态编译成功；
- 主图包含 W14 目标节点和 response subgraph；
- 手造工单完成标准化、分类结果注入、澄清和收尾；
- 没有真实模型调用。

未执行：

- pytest；
- DeepSeek 分类调用；
- response subgraph 的真实路径；
- 数据库、向量检索和人工审批。

## 13. 本 Session 的收益

### 学习收益

- 从“会写一个 node”提升到“会设计业务 state”；
- 理解 graph state 和 structured output 不是同一个东西；
- 学会把模型决策限制在有限业务结果内；
- 学会识别确定性逻辑，避免把所有事情交给 LLM；
- 学会在实现前用 Node I/O 表检查边界。

### 工程收益

- 后续节点共享一份稳定的业务契约；
- 状态可序列化，未来可以接 checkpoint；
- 错误有稳定 code，未来可以接 SSE 和 API；
- W13 现有 CLI 不因 W14 的枚举变化而被破坏；
- response subgraph 有明确边界，后续可以独立实现和测试。

## 14. 自测题

1. 为什么 `TicketAgentState` 使用 `TypedDict`，而分类结果使用 Pydantic？
2. 为什么模型 client 不能放到 state？
3. 为什么 `missing_fields` 应该进入 state，而 `reason` 可以只停留在结构化结果中？
4. 为什么 `normalize_ticket` 不应该调用 LLM？
5. 为什么 W14 要保留两个不同命名的分类模型？
6. 如果 `response_subgraph` 把完整政策文档放进 state，会带来什么问题？
7. 为什么高风险在 W14 只输出 `requires_approval=True`，而不直接调用退款工具？

能够用当前代码和离线 Demo 的输出回答这些问题，才算掌握本 Session。

## 15. 下一步

W14 Session 2 已实现：

```text
normalize_ticket
  → classify_ticket
  → clarification branch
```

本节接入结构化分类模型，并验证信息缺失的工单不会进入 response subgraph。详细教程和命令见：

`tutorials/w14-session-02-classification-clarification.md`
