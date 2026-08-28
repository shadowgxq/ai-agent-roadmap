# W14 Session 2｜分类驱动澄清分支

## 1. 本 Session 的位置

Session 1 冻结了 `TicketAgentState` 和主图骨架，但 `classify_ticket` 还没有接入真实模型。Session 2 把这份契约推进成可运行的业务分支：模型只做结构化理解，LangGraph 条件边决定工单继续走澄清还是进入回复子图。

本节的实现范围仍然不包含政策检索、回复生成和风险评估。Session 2 当时让完整输入进入 `response_subgraph` 占位边界；这些节点已在 Session 3 实现，当前完整流程见 `tutorials/w14-session-03-policy-response-risk.md`。

## 2. 学习目标

完成本节后，你应该能够：

1. 解释 `with_structured_output(TicketWorkflowClassification)` 如何限制模型输出；
2. 解释为什么模型不直接返回节点名，而由 Python 条件边控制下一步；
3. 说明 `needs_clarification` 和 `missing_fields` 的关系；
4. 通过 trace 判断信息缺失工单是否进入了 `response_subgraph`；
5. 区分“分类调用成功”“分支路径正确”和“完整回复流程已完成”。

## 3. 实际调用链

```text
CLI
  → AgentSettings / create_chat_model
  → create_ticket_graph(model)
  → normalize_ticket                 # 代码：裁剪、校验、拼接文本
  → classify_ticket                  # DeepSeek：一次结构化分类
  → route_after_classification       # 代码：读取 missing_fields
      ├─ 有缺失字段
      │    → build_clarification     # 代码：生成精确补充问题
      │    → finalize
      └─ 无缺失字段
           → response_subgraph       # 当前只验证进入边界
           → retrieve_policy_stub    # 当前显式返回未就绪
           → finalize
```

这里有两个重要边界：

- 模型返回的是 `category`、`priority`、`needs_clarification`、`missing_fields` 和 `reason`，不是 `"build_clarification"` 这样的内部节点名；
- state 持久化 `missing_fields`，不重复保存 `needs_clarification`。图使用 `bool(missing_fields)` 作为可审计的澄清依据，并要求模型保持 `needs_clarification == bool(missing_fields)`。

## 4. 本节实现

### 4.1 分类提示词与结构化输出

`/home/gxq/ai-agent-roadmap/support-agent/src/support_agent/graphs/ticket.py` 中的 `classify_ticket` 通过图工厂注入的模型调用：

```python
classifier = model.with_structured_output(
    TicketWorkflowClassification,
    method="function_calling",
)
```

模型只能返回有限的 category、priority 和 canonical `missing_fields`。分类节点只把后续业务真正需要的字段写回 state，不把 `reason` 当作客服回复，也不把模型 client 放进 state。

如果模型说需要澄清却没有返回 `missing_fields`，节点会返回 `MISSING_CLASSIFICATION`。没有精确字段就不能生成精确问题，也不能继续猜测。`missing_fields` 使用 `order_id`、`refund_reason`、`account_email` 等稳定字段名，`build_clarification` 再由代码映射成用户可读问题。

### 4.2 条件边

`route_after_classification` 的责任很小：

```python
if state.get("missing_fields"):
    return "clarification"
return "response"
```

这体现了“模型理解、代码编排”：模型识别缺什么，条件边只根据 state 做确定性分支。后续若增加审批、重试或人工补充，不需要让模型了解内部图结构。

### 4.3 八个固定样例

`/home/gxq/ai-agent-roadmap/support-agent/src/support_agent/ticket_samples.py` 固定了 8 个样例：3 个信息缺失样例覆盖退款、账户和技术问题，5 个信息完整样例覆盖账单、产品、技术、账户和其他问题。

验收重点不是要求模型生成某个固定中文句子，而是：

```text
信息缺失 → build_clarification ∈ visited_nodes
信息缺失 → response_subgraph ∉ visited_nodes
信息完整 → response_subgraph ∈ visited_nodes
```

在 Session 2 的验收时，完整输入会在响应子图的占位节点失败。因此当时“进入响应子图”与“已经能生成客服回复”是两个独立结论；Session 3 已替换该占位实现。

## 5. 可执行命令

在 WSL 中运行单个样例并查看节点路径：

```bash
cd /home/gxq/ai-agent-roadmap/support-agent
uv run support-ticket-workflow --sample missing-refund --trace
```

运行全部 8 个样例：

```bash
uv run support-ticket-workflow --all-samples
```

运行自定义工单：

```bash
uv run support-ticket-workflow \
  --subject "订单重复扣款" \
  --description "订单 12345 被同一张卡扣款两次，请核查。" \
  --trace
```

这些命令会调用真实配置中的 DeepSeek 模型。`--all-samples` 默认每个样例调用一次分类模型；不会调用当前未就绪的回复生成模型。

## 6. 如何阅读输出

缺信息样例的关键输出应类似：

```text
normalize_ticket → classify_ticket → build_clarification → finalize
```

并且结果中应有：

```json
{
  "status": "completed",
  "missing_fields": ["order_id"],
  "assertion": {
    "status": "passed"
  }
}
```

完整样例的关键输出应类似：

```text
normalize_ticket → classify_ticket → response_subgraph → finalize
```

Session 2 当时的结果中的 `error_code` 是 `RESPONSE_SUBGRAPH_NOT_READY`，这证明了路由正确，但不代表回复流程已经完成。现在应阅读 Session 3 教程查看完成后的 response subgraph 结果。

### 6.1 本次真实执行结果

本次先运行了完整 8 条样例，发现产品使用咨询被模型误判为 technical；补充 category 判定边界后，仅重跑该失败样例，得到以下最终路径证据：

| 样例 | 实际 category | 实际路径 | 验收 |
|---|---|---|---|
| `missing-refund` | `billing` | 澄清 | 通过 |
| `missing-account` | `account` | 澄清 | 通过 |
| `missing-technical` | `technical` | 澄清 | 通过 |
| `complete-billing` | `billing` | response 子图边界 | 通过 |
| `complete-product` | `product` | response 子图边界 | 通过 |
| `complete-technical` | `technical` | response 子图边界 | 通过 |
| `complete-account` | `account` | response 子图边界 | 通过 |
| `complete-other` | `other` | response 子图边界 | 通过 |

完整样例的终态都是 `failed / RESPONSE_SUBGRAPH_NOT_READY`，这是当前 Session 3 尚未实现的占位边界；它不影响本 Session 对分类和路由的验收。这个过程也暴露了一个重要事实：Pydantic 可以保证结构合法，但不能保证模型的业务分类一定正确，所以仍需要固定样例和 trace。

## 7. 本 Session 的收益

### 学习收益

- 掌握“structured output 是业务理解契约，不是整个 Agent 流程”的边界；
- 掌握 conditional edge 如何读取 state 选择下一节点；
- 理解信息缺失是一个正式业务状态，而不是让模型自由补全的空白；
- 学会用节点 trace 验收路径，而不是只看最终文本。

### 工程收益

- 不完整工单会在回复生成前停止，避免无意义的后续模型调用；
- 澄清问题由代码从 `missing_fields` 映射生成，输出稳定、可测试；
- 分类模型可替换，图的业务分支不需要跟着 provider SDK 改；
- 完整输入和未就绪能力的边界显式可见，为 Session 3 接入 policy corpus 留出位置。

## 8. 验收标准

- [x] `classify_ticket` 使用 `TicketWorkflowClassification` 结构化输出；
- [x] 分类只产生允许的 category 和 priority；
- [x] `needs_clarification=True` 时必须有 `missing_fields`，否则返回 `MISSING_CLASSIFICATION`；
- [x] 3 个信息缺失样例均未进入 `response_subgraph`；
- [x] 完整样例进入 `response_subgraph`，当前边界错误码明确；
- [x] 每个样例只进行一次分类模型调用；
- [x] W13 的 `support-agent` 和 `support-routing` CLI 仍可加载。

## 9. 自测题

1. 为什么分类模型返回 `missing_fields`，而不是直接返回 `next_node`？
2. 如果 `needs_clarification=True` 但 `missing_fields=[]`，为什么不能生成一个泛化的“请补充更多信息”？
3. 为什么完整样例进入 `response_subgraph` 后仍然可以是失败状态？
4. 为什么用 `--trace` 验收比只看最终 JSON 更可靠？
5. 如果把 `build_clarification` 也改成模型生成，可能新增什么不稳定性？

## 10. 下一步

Session 3 已实现固定 policy corpus、证据引用和 response subgraph 内的回复生成与风险评估，并真实验证了“查询账单”与“代我退款”的证据和风险结果。详见 `tutorials/w14-session-03-policy-response-risk.md`。
