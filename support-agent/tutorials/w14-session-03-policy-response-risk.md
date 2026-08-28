# W14 Session 3｜政策证据、回复生成与风险评估

## 1. 本 Session 的位置

Session 2 已经让分类结果能够决定“澄清还是继续处理”。Session 3 把完整工单接入真正的 response subgraph：先取得固定政策证据，再生成有引用的回复草稿，最后由代码硬规则和结构化风险模型共同评估风险。

本节仍然不执行退款、账户修改、数据删除等副作用。高风险只写入 `requires_approval=True`，人工审批和外部写操作属于后续 W15。

## 2. 学习目标

完成本节后，你应该能够：

1. 解释为什么 state 中保存 `EvidenceRef`，而不是完整政策文档；
2. 说明回复节点如何限制模型只能使用政策证据；
3. 说明为什么回复草稿必须包含 `source_id` 引用；
4. 解释硬规则与 LLM 风险结果如何合并；
5. 区分“回复生成成功”“风险评估完成”和“副作用已执行”。

## 3. 实际调用链

```text
normalize_ticket
  → classify_ticket                  # 结构化分类
  → route_after_classification
  → response_subgraph
      → retrieve_policy_stub         # 代码：固定内存政策库
      → draft_response                # LLM：只基于 evidence 生成
      → assess_risk                   # 代码硬规则 + LLM structured output
  → finalize
```

澄清分支仍然在分类后提前结束，因此缺信息工单不会消耗回复和风险模型调用。

## 4. 固定政策证据

`/home/gxq/ai-agent-roadmap/support-agent/src/support_agent/policy_corpus.py` 定义 W14 专用的 `POLICY_CORPUS`。它的类别与 W14 的 `TicketCategory` 一致：`billing`、`account`、`product`、`technical`、`other`。

每条证据都是小型引用对象：

```python
EvidenceRef(
    source_id="billing_refund_001",
    title="账单与退款处理政策",
    snippet="退款申请需要核对订单号、支付记录和退款原因。",
)
```

`retrieve_policy_stub` 是确定性节点，不调用模型，只根据分类结果返回 1–3 条引用。W13 的 `support_agent/tools/policy.py` 保持不变，因为它使用另一份 `refund` / `billing` 工具契约；W14 不把两个类别模型强行混合。

## 5. 回复生成边界

`draft_response` 将工单文本和 evidence 引用传给模型，并明确要求：

- 不能编造证据中没有的政策、承诺或处理结果；
- 回复必须引用至少一个 `source_id`；
- 证据不足时要说明无法确认，并提出补充信息；
- 只输出客户可见的回复，不输出分析过程。

代码还会检查回复中是否出现某个真实 `source_id`。模型没有引用证据时，节点返回 `DRAFT_GENERATION_FAILED`，不会把未验证的文本当作成功结果。

## 6. 风险评估边界

### 6.1 代码硬规则

`_hard_risk_assessment` 先识别明确的副作用请求，例如：

- “代我退款”或“直接帮我退款”；
- “帮我修改账户”；
- “帮我删除数据”。

命中后直接产生 high 风险和 `requires_approval=True`。这部分不能被后续模型降级。

### 6.2 结构化模型结果

模型通过：

```python
model.with_structured_output(
    RiskAssessment,
    method="function_calling",
)
```

返回 `low | medium | high`、风险原因和审批标记。代码按 `low < medium < high` 取硬规则和模型结果中的更高等级，并合并去重后的原因。

因此即使模型错误返回：

```json
{
  "risk_level": "low",
  "requires_approval": false
}
```

只要用户明确要求执行退款，最终仍然是：

```json
{
  "risk_level": "high",
  "requires_approval": true
}
```

## 7. 可执行命令

查询账单，查看完整节点 trace：

```bash
cd /home/gxq/ai-agent-roadmap/support-agent
uv run support-ticket-workflow --sample query-billing --trace
```

验证“代我退款”的高风险边界：

```bash
uv run support-ticket-workflow --sample request-refund-action --trace
```

一次运行两条 Session 3 风险样例：

```bash
uv run support-ticket-workflow --risk-samples
```

完整回复流程每条完整工单通常包含三次模型调用：分类、回复、风险；固定政策检索不调用模型。

## 8. 本次真实执行结果

本次使用真实 DeepSeek 配置执行了两条风险样例。期间先修复了 trace 对 `EvidenceRef` 的序列化问题，以及模型漏写引用时的提示约束；最终关键结果如下：

| 样例 | 分类 | 证据 | 风险 | 审批 | 终态 |
|---|---|---|---|---|---|
| `query-billing` | `billing` | `billing_refund_001`、`billing_charge_001` | `low` | `false` | `completed` |
| `request-refund-action` | `billing` | `billing_refund_001`、`billing_charge_001` | `high` | `true` | `completed` |

两条路径都经过：

```text
normalize_ticket → classify_ticket → response_subgraph → finalize
```

退款样例的模型风险结果与代码硬规则一致；离线测试另外验证了即使模型返回 low，硬规则仍会保留 high 和审批要求。

## 9. 本 Session 的收益

### 学习收益

- 掌握 evidence-grounded generation 的最小实现；
- 理解结构化风险结果仍然需要业务规则兜底；
- 学会把“模型建议”和“最终业务状态”分成两层；
- 看懂 response subgraph 如何在主图中形成独立边界。

### 工程收益

- 回复可以追溯到固定 `source_id`；
- 未引用证据的回复不会被当成成功结果；
- 高风险副作用不能被模型自我降级；
- 未来接入人工审批时已有明确的 `requires_approval` 落点。

## 10. 验收标准

- [x] 每个 W14 类别都有固定 policy evidence；
- [x] `draft_response` 至少引用一个 `source_id`；
- [x] 没有证据或没有引用时返回明确错误码；
- [x] 硬规则命中退款/账户/删除操作时最终风险至少为 high；
- [x] “查询账单”真实运行得到 low 且无需审批；
- [x] “代我退款”真实运行得到 high 且需要审批；
- [x] W14 不执行外部副作用。

## 11. 自测题

1. 为什么 `EvidenceRef` 只保存 snippet，而不是完整政策原文？
2. 如果模型生成了一段正确但没有引用 ID 的回复，为什么仍然不能直接放行？
3. 为什么风险评估要取硬规则和模型结果中的更高等级？
4. 为什么 `requires_approval=True` 还不等于已经暂停图或执行人工审批？
5. 如果政策库查不到分类，应该让模型自由回答吗？

## 12. 下一步

Session 4 将实现 `GraphEventAdapter`：把 LangGraph 内部节点和模型事件转换为稳定的应用事件，避免前端直接依赖 SDK message 或内部 node path。
