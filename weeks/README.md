# weeks/ —— W1–W20 学习计划·周执行文档索引

> W1–W12 主计划见 [`../AI-Agent-工程师转型路线-12周.md`](../AI-Agent-工程师转型路线-12周.md)；W13–W20 企业级强化见 [`../AI-Agent-工程师企业强化路线-W13-W20.md`](../AI-Agent-工程师企业强化路线-W13-W20.md)。本目录是每周的细化执行文档：概念讲透、资料给链接、任务拆到 session、验收可打勾。
> 每份文档统一 7 节结构:核心要掌握 / 学习资料 / 落地执行(按 session)/ 自测题 / 验收 checklist / 常见坑速查 / 本周产出物。

## 文档索引

| 文档 | 主题 | 里程碑产出 |
|------|------|-----------|
| [W01.md](W01.md) | Messages API + Streaming + 多轮对话 | FastAPI SSE 流式聊天服务 + 精确 token/费用统计 |
| [W02.md](W02.md) | Tool Use + 结构化输出 | 通用工具注册表 + 完整 tool use 回路 + 并发多工具 |
| [W03.md](W03.md) | Agent Loop 核心 ★ | `agent-mini` CLI 能在真实仓库修 bug 并自测 |
| [W04.md](W04.md) | Evals 起步 + 可靠性 ★ | 10 case 评估集 + 基线数字 + 重试/超时/费用熔断 |
| [W05.md](W05.md) | Workflow 编排(手写) | evaluator-optimizer / routing / chaining 三种模式 |
| [W06.md](W06.md) | SubAgent + Checkpoint | context 隔离 + `--resume` + 20 case +(P1)最小 Web 查看器 |
| [W07.md](W07.md) | 上下文工程 + RAG | auto-compact + RAG vs agentic search 对照数据 |
| [W08.md](W08.md) | MCP | **开源 MCP server**(交付物 2)+ MCP client 架构 |
| [W09.md](W09.md) | 可观测性 + Evals 深化 | Langfuse trace + 25–30 case + LLM-as-judge + 对抗用例 |
| [W10.md](W10.md) | 安全加固 + 成本工程 + 技术博客 | 权限护栏 + caching/router 成本对比数据 + **博客发布**(交付物 4) |
| [W11-12.md](W11-12.md) | 产品化冲刺:Web 版上线 | **公开 URL 的 Web 版 agent**(交付物 1 完全体) |
| [W13.md](W13.md) | LangChain / LangGraph 框架映射 | `support-agent` 起步 + 手写与框架对照 |
| [W14.md](W14.md) | LangGraph 业务编排 | 工单 `StateGraph` + typed state + streaming |
| [W15.md](W15.md) | 持久化 + Human-in-the-loop | PostgreSQL checkpointer + 审批恢复 + 幂等副作用 |
| [W16.md](W16.md) | 企业 RAG | pgvector + FTS 混合检索 + 引用 + retrieval eval |
| [W17.md](W17.md) | 生产后端 | PostgreSQL/Redis/Celery + 任务状态机 + 幂等/取消/恢复 |
| [W18.md](W18.md) | 鉴权、多租户与安全 | RBAC + tenant scope + MCP 工具权限 + 审计 |
| [W19.md](W19.md) | React 企业工作台 | 工单/引用/审批/恢复/历史的产品闭环 |
| [W20.md](W20.md) | E2E 质量闭环 + 求职 | 30 case + Langfuse + 部署 + 简历/口述 |

## 使用说明

1. **每周开始**:先通读当周文档的「核心要掌握」和「落地执行」,再排本周 session 到日历上(每周 5–6 个,W11–12 为两周 10–12 个)。
2. **每个 session 结束**:对照该 session 的「✅ 完成标志」自检,做不到就不算完成。
3. **每周结束**:过一遍当周文档的「验收 checklist」,然后回主文档第 12 节勾选对应进度项;验收不过不进下一周。
4. **P1 任务**:时间富余才做;W9 起若目标公司考算法,刷题时间从当周 P1 里挤。
5. **踩坑即学习**:遇到问题先查当周「常见坑速查」——那里每条都写了怎么发现、怎么解决。
6. **主线仓库**:W3 起所有代码都在 `agent-mini` 单仓库演进,每周至少 3 次有意义的 commit,W4 起每周至少 1 条 `evals/LOG.md` 实验记录。
7. **W11-12 是合并文档**:产品化冲刺按两周排期(20–30h、10–12 个 session),中途不做周切换,只在第 11 周末对照文档做一次进度校准(容器隔离必须已完成)。
8. **资源以周文档链接为准**:每周文档的「学习资料」都精确到 URL 和要读的章节,不要自行发散找教程——主计划的原则是少而精、反复读。
9. **W13–W20 是递进门槛**:W12 的 P0 未验收不开 W13；W13 起每周只增加一种主复杂度，当周 P0 未通过就顺延，不跳级。
10. **前端只有一套**:W11 起统一扩展 `frontend/` 的 Vite + React + TypeScript 工程；不新建 Next.js 或第二套 Web 应用。
