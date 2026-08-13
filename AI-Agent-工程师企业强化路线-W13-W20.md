# AI Agent 工程师企业级强化路线（W13–W20）

> 从“能手写 Agent 并做出产品”进阶到“能用主流框架交付企业 Agent 系统”。
> 适用于完成 W1–W12 后，以国内互联网 / AI 创业公司的 **Agent 全栈应用工程师**为目标，每周投入 10–15 小时，边学边投。

---

## 1. 阶段定位

W1–W12 已经建立四类底层能力：

- 手写 agent loop、tool use、workflow、subagent 和 auto-compact。
- 用 eval、trace、成本与安全护栏管理模型不确定性。
- 用 FastAPI + SSE 暴露 Agent 运行过程。
- 用现有 `frontend/` 的 Vite + React + TypeScript 页面展示 Agent 事件流。

W13–W20 不再重复这些原理，只补企业落地缺口：

1. 用 LangChain / LangGraph 表达团队可维护的状态流。
2. 用 PostgreSQL、Redis、Celery 承载持久任务、失败恢复与并发。
3. 做可评估的企业 RAG，而不是只做“能问答”的 demo。
4. 补齐鉴权、多租户、人工审批、工具权限与审计。
5. 用同一个 React 工程完成企业工作台，不引入 Next.js。

## 2. 学习深度：一层验收后再进下一层

| 层级 | 要解决的问题 | 达标标志 | 对应周 |
|---|---|---|---|
| L1 原理层 | Agent 为什么这样运行 | 能手写并调试核心机制 | W1–W12 已完成 |
| L2 框架映射层 | 框架替代了哪些手写代码 | 能对照实现、说清取舍 | W13 |
| L3 业务编排层 | 如何设计可控的企业 Agent 流程 | 状态、分支、子图和事件都可追踪 | W14 |
| L4 长任务层 | 怎么暂停、审批、恢复且不重复产生副作用 | 服务重启后可恢复，工具写入幂等 | W15 |
| L5 数据与服务层 | 怎么检索、持久化、异步执行与并发 | RAG 和任务系统都有客观验收 | W16–W17 |
| L6 企业边界层 | 怎么限制用户、租户、数据与工具权限 | 越权、注入和未审批副作用均被拦截 | W18 |
| L7 交付层 | 怎么让用户真正完成业务闭环 | React 工作台、eval、观测和部署完整 | W19–W20 |

**升级规则**：当周 P0 验收未通过，不得因为“时间到了”进入下一周。学习周数可以顺延，学习深度不能跳级。

## 3. 框架学习权重

| 技术 | 要求 | 必学内容 | 不学 / 按 JD 再学 |
|---|---|---|---|
| **LangGraph** | P0，达到项目级熟练 | `StateGraph`、typed state、reducer、conditional edge、`Command`、streaming、subgraph、checkpointer、store、`interrupt()` | 不追求所有高级 API |
| **LangChain v1** | P0，达到正确使用 | model/tool 接口、`create_agent`、structured output、middleware、retriever | 不学 legacy Chain 大全，不背组件 API |
| **Langfuse** | P0，继续现有选型 | trace、span、score、dataset/experiment、成本和延迟 | 不为框架搭配额外迁移到 LangSmith |
| Claude / OpenAI Agents SDK | P1，会对比 | 对照 loop、tool、handoff、guardrail、trace | 不做第三个主项目 |
| Dify / Coze / LlamaIndex | JD 触发 | 30 个目标 JD 中出现率达 20% 再安排 4–6h 专项 | 不因教程热度自动加入主线 |

## 4. 主线项目：企业知识库 + 工单协同 Agent

### 4.1 仓库边界

```text
agent-mini/                 # W1–W12 手写 Agent，保留为原理作品
support-agent/              # W13–W20 新增的 LangGraph 企业后端
frontend/                   # 继续使用现有 Vite + React + TypeScript
  src/pages/agent/          # 原 coding agent 演示，保留
  src/pages/support/        # W19 新增的工单工作台
```

- 不把 `agent-mini` 重构成 LangGraph；两个项目分别证明“懂原理”和“能企业交付”。
- 不新增 Next.js、Tailwind 或第二套前端。新页面遵循 `frontend/AGENTS.md` 和 `frontend/docs/frontend/`。
- `support-agent/` 使用 Python 3.12、FastAPI、LangChain v1、LangGraph、Pydantic v2、SQLAlchemy 2、Alembic、PostgreSQL + pgvector、Redis + Celery、Langfuse。

### 4.2 业务流

```text
创建工单
  → 分类与缺失信息判断
  → 企业知识检索
  → 生成带引用的回复与执行计划
  → 风险分级
  → 低风险：结束
  → 高风险：interrupt 等待人工审批
      → 批准：通过 MCP 更新模拟 CRM
      → 拒绝 / 修改：带反馈重新生成
  → 写入审计记录
```

### 4.3 状态与标识约定

`TicketAgentState` 只放图执行需要且可序列化的数据：

- `organization_id`、`user_id`、`ticket_id`、`run_id`、`thread_id`。
- 工单内容、分类、缺失信息、检索证据、草稿、风险结果、审批结果、工具结果和错误。

四个 ID 不得混用：

- `ticket_id`：业务工单。
- `run_id`：一次 Agent 执行，供 API、事件和可观测性关联。
- `thread_id`：LangGraph checkpointer 的持久化游标，暂停后用同一 ID 恢复。
- `organization_id`：租户边界，只能从服务端鉴权上下文注入，不信任请求 body。

Run 业务状态固定为：

```text
queued → running → waiting_approval → running → succeeded
                   └→ failed
queued/running/waiting_approval → cancelled
```

LangGraph checkpointer 保存完整图状态；业务 `runs` 表只保存查询和 UI 需要的投影，不复制一份完整 state。

### 4.4 API 与 SSE 契约

P0 接口固定为：

| 接口 | 用途 |
|---|---|
| `POST /api/v1/auth/login` | 登录并写入短期 `HttpOnly` cookie |
| `POST /api/v1/knowledge/documents` | 上传 Markdown / 文本型 PDF 并创建入库任务 |
| `GET /api/v1/knowledge/documents` | 查看文档与索引状态 |
| `POST /api/v1/tickets` | 创建工单 |
| `GET /api/v1/tickets` / `GET /api/v1/tickets/{ticket_id}` | 租户内工单列表与详情 |
| `POST /api/v1/tickets/{ticket_id}/runs` | 启动一次 Agent 运行 |
| `GET /api/v1/runs/{run_id}` | 查看 run 当前投影状态 |
| `GET /api/v1/runs/{run_id}/events` | SSE 实时流与历史回放 |
| `POST /api/v1/runs/{run_id}/approvals` | `approve` / `reject` + `feedback`，恢复 interrupt |
| `POST /api/v1/runs/{run_id}/cancel` | 取消排队或运行中任务 |

SSE 保留现有前端熟悉的 envelope：

```json
{
  "sequence": 12,
  "run_id": "run_xxx",
  "event": "approval_required",
  "occurred_at": "2026-08-12T10:00:00Z",
  "data": {}
}
```

- SSE `id` 等于 `sequence`，后端根据 `Last-Event-ID` 从持久化事件表续传。
- P0 事件类型：保留现有 `text`、`tool_call`、`tool_result`、`context_usage`、`done`，再加入企业业务需要的 `status`、`retrieval`、`diff`、`approval_required`。
- 前端只把显式 `done` 视为终态；断流不代表任务失败或完成。
- 生产部署使用同域 `/api/v1` 反向代理 + `HttpOnly` cookie，避免 token 进入 `localStorage`，也保持原生 `EventSource` 可用。

### 4.5 数据边界

业务表至少包含：`organizations`、`users`、`memberships`、`knowledge_bases`、`documents`、`chunks`、`tickets`、`runs`、`run_events`、`approvals`、`tool_actions`、`audit_events`。

- 所有业务查询都必须显式带 `organization_id`；不接受“先按 ID 查出再检查租户”的漏洞式写法。
- `tool_actions.idempotency_key` 建唯一索引，保证 interrupt 恢复、worker 重试或节点重放不重复更新 CRM。
- 文档 chunk 保存 `organization_id`、`knowledge_base_id`、`document_id`、页码/标题路径和版本，以支撑租户过滤与引用溯源。

## 5. W13–W20 路线总览

| 周 | 学习深度 | 主要产出 | 细化文档 |
|---|---|---|---|
| W13 | 框架映射 | 手写机制 ↔ LangChain / LangGraph 对照，`support-agent` 起步 | [W13](weeks/W13.md) |
| W14 | 业务编排 | 工单 Agent `StateGraph`、typed state、分支、子图和 streaming | [W14](weeks/W14.md) |
| W15 | 长任务 | PostgreSQL checkpointer、`interrupt`审批、恢复和副作用幂等 | [W15](weeks/W15.md) |
| W16 | 企业 RAG | 文档入库、pgvector + FTS 混合检索、引用和检索 eval | [W16](weeks/W16.md) |
| W17 | 生产后端 | SQLAlchemy/Alembic、Redis + Celery、幂等、取消、重试和并发 | [W17](weeks/W17.md) |
| W18 | 企业边界 | 鉴权、RBAC、多租户、MCP 工具权限、PII 与审计 | [W18](weeks/W18.md) |
| W19 | 产品交付 | 在现有 React 中完成工单、引用、审批、恢复和历史 | [W19](weeks/W19.md) |
| W20 | 质量与求职 | 30 个 E2E eval、Langfuse、并发检查、部署、README 与面试口述 | [W20](weeks/W20.md) |

## 6. 每周固定节奏

每周 10–15 小时按下列比例使用：

- 7–9h：主线项目 P0 任务。
- 2h：官方文档与原理对照。
- 1–2h：eval、失败分类和实验记录。
- 1–2h：求职线，每周精读 3 个 JD、投递 5 个高匹配岗位、完成 1 次项目口述。

方法规则：

1. **先契约，后代码**：先定 state、API、event 和错误边界。
2. **一周只增加一种主复杂度**：W14 不同时加数据库，W16 不同时加权限。
3. **官方文档优先**：框架 API 只从当前官方文档学，不用过期 LangChain 教程。
4. **评估驱动**：检索、prompt、router 和工具策略的优化必须有数据。
5. **失败才是学习单元**：每周至少选一个失败 trace，形成“现象 → 原因 → 改动 → 数据”。
6. **P1 不得阻塞 P0**：模型多供应商、OCR、reranker、长期 memory 和算法题按周文档说明执行。

## 7. 总验收

### 框架与编排

- [ ] 能用现有 `agent-mini` 对照说清 LangChain harness 和 LangGraph runtime 的责任。
- [ ] 工单 Agent 的确定性步骤与 LLM 决策步骤边界清晰，state 可序列化。
- [ ] 服务重启后能从 `waiting_approval` 恢复，重试不会重复执行 CRM 写入。

### RAG 与质量

- [ ] 至少 50 条检索评估数据，Recall@5 达到 0.80，并保留基线与失败分类。
- [ ] 抽查至少 20 个回答，引用正确率达到 90%。
- [ ] 端到端 eval 至少 30 条，覆盖分类、检索、审批、恢复、权限与对抗输入。

### 企业工程

- [ ] 重复请求不重复创建 run，worker 失败后可恢复到一致终态。
- [ ] 所有外部写工具需要审批、具有幂等键并写审计日志。
- [ ] 跨租户数据访问全部被拒绝，15 个安全对抗用例中未审批副作用为 0。

### 产品与求职

- [ ] 现有 React 工程能完成“创建工单 → 查看引用 → 审批 → 更新 CRM → 查看审计”闭环。
- [ ] SSE 断线重连不丢事件、不重复渲染、不把断流误判为终态。
- [ ] 有公开 demo、架构图、数据化 README、演示视频和 15 分钟项目口述稿。
- [ ] 完成 30 个目标 JD 技能矩阵，简历同时展示 `agent-mini` 和企业工单 Agent。

## 8. 明确不做

- 不拆微服务，不学 Kubernetes，先用模块化单体 + worker。
- 不做模型训练、微调、GPU 推理或深度学习数学。
- 不支持扫描 PDF / OCR；W16 P0 只处理 Markdown、纯文本和有文本层的 PDF。
- 不为了“多 Agent”而多 Agent；子图只在责任、state 或复用边界清晰时使用。
- 不把前端 SSR、SEO 或 Next.js 当作转型学习项，企业工作台继续使用 React SPA。
