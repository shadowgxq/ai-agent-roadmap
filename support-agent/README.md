# Support Agent：W13–W21 企业工单示例

系统将工单理解、企业知识检索、风险分级、人工审批和模拟 CRM 写入串成业务闭环。已有 React 页面位于 `/support`。只提供受控模拟 CRM，不提供任意 Shell、生产支付或真实客户系统写入。

## 架构与关键契约

```text
React → Nginx → FastAPI → PostgreSQL：tickets / runs / events / approvals / audit / outbox
                                  ↓ outbox + Celery scheduler
                              Redis → Worker → LangGraph + PostgreSQL checkpoint
                                                  ├─ W19 hybrid retrieval / evidence
                                                  ├─ risk → interrupt → human decision
                                                  └─ approved mock CRM + atomic audit
```

- `ticket_id` 表示业务对象，`run_id` 表示一次执行，`thread_id` 表示独立 checkpoint。队列与 trace 不替代业务状态。
- 身份来自服务端配置的账号与签名 HttpOnly Cookie。租户过滤进入 repository 和两条检索 SQL；客户端不能提交 `organization_id` 覆盖身份。
- 业务状态为 queued / running / waiting_approval / succeeded / failed / cancelled。请求使用 `Idempotency-Key`，审批绑定 `proposal_hash` 和修订轮次。
- 受控 CRM 写入检查租约、取消状态、参数白名单和持久审批。副作用、幂等记录、审计在同一数据库事务中提交；unknown/pending 写入结果不会自动重放。
- SSE 的 `sequence` 是续传和去重依据，持久 `done` 才是终态。`event-history` 提供有限的历史快照，等待审批时也能导出。
- Worker 使用心跳和有限重试；过期租约的任务由 scheduler 恢复，旧 Worker 不能提交结果。该模型适用于合作式宿主和模拟 CRM，不是操作系统沙箱。

## 本地检查与 Eval

需要 Python 3.12 和 uv。以下命令只使用本地测试替身，不启动服务、不调用模型、不上传 trace：

```bash
cd support-agent
uv sync --group dev --frozen
uv run pytest -q tests/test_w21_catalog.py tests/test_w21_report.py tests/test_w21_telemetry.py tests/test_w21_faults.py tests/test_w21_experiments.py tests/test_w21_deployment.py
uv run support-eval --config evals/w21_offline_recommended.json --output /tmp/support-eval.json
uv run support-eval-experiments --output /tmp/support-experiments.json
uv run alembic upgrade head --sql > /tmp/support-migration.sql
```

30-case 分布：8 分类/澄清、8 检索/引用/无答案、5 低风险、4 高风险审批、3 恢复/幂等、2 跨租户/注入。case 和知识库快照使用 SHA-256 冻结，每次运行独立分配 run、thread、ticket 和工具状态。

`uv run pytest -q tests` 默认只运行离线检查；W15 PostgreSQL 集成用例保持跳过。数据库用例必须在明确允许访问已运行数据库时显式添加 `--run-integration`，该选项本身不会启动服务，也不调用模型。

`support-eval` 默认运行真实 ticket Graph，但模型、检索和 CRM 是明确的本地替身。默认词项匹配基线为 29/30；离线推荐配置为 30/30。费用和人工引用正确率为 `null`，`production_quality_verified=false`。报告检查分类、文档 ID、引用 ID、审批、工具审计、事件序号和唯一终态，不用回答流畅度代替这些断言。

固定实验结果位于 `evals/w21_offline_experiments.json`：

| 对照 | 单一变量 | 本地观测 | 适用边界 |
|---|---|---|---|
| 降低无关召回 | min_overlap 1 → 2 | 29/30 → 30/30，平均证据字符数减少 169.9 | 词项检索替身 |
| 缩小上下文 | top-k 5 → 1 | 保持 30/30，平均证据字符数再减少 55.8 | 词项检索替身 |
| 过度过滤反例 | min_overlap 2 → 100 | 通过率下降约 66.7 个百分点 | 拒绝此配置 |

这些数据不能证明 pgvector/FTS 的真实质量或 API 成本变化。W18 single/multi-agent、W19 retrieval、W21 business E2E 各自报告；可用 `--w18-report`、`--w19-report` 加载既有结果，缺失时保持为空。

自由文本的 claim support 仍需独立审查；引用 ID 有效不等于主张被证据支持。已有 `support-knowledge-audit generate/score` 用于 20 个回答的明确人工标注。`--recorded observations.json` 可对独立采集的生产观测运行同一套断言，不能把离线记录改名当作真实观测。

## 运行配置与 Docker Compose

运行前准备 `support-agent/.env`，沿用 `.env.example` 的字段：模型与 embedding 凭据、随机的 32 字符以上 session secret、服务端账号及 scrypt 密码 hash。用 `uv run support-app hash-password` 在本地生成 hash；账号角色为 viewer / operator / approver / admin。生产侧永远不接收客户端选定的租户或角色。

`compose.support.yaml` 是独立演示栈，使用独立 PostgreSQL/Redis volumes，不覆盖 W12/W15 学习环境。数据库和 broker 没有宿主公开端口，前端仅绑定 `127.0.0.1:8082`。启动命令由使用者明确执行：

```bash
docker compose -f compose.support.yaml config --quiet
docker compose -f compose.support.yaml up --build -d
```

迁移服务先执行 Alembic，再初始化 checkpointer；API 依赖迁移成功和 Redis 健康，Worker/scheduler/前端依赖 API 健康。前端访问 `http://localhost:8082/support`。Nginx 关闭 SSE buffering；API 有 liveness/readiness，Worker 检查自己的 broker ping，scheduler 的检查只证明进程存在，不证明调度已完成。

本地 HTTP 配置使用非 Secure Cookie；若部署 HTTPS，必须将 Compose 中 `SUPPORT_APP_SECURE_COOKIE` 改为 true，并配置可信 Origin、TLS、受限数据和强账号密码。当前 Compose 是本机模拟演示，不是公网生产配置。

## 真实 E2E 与 Trace：显式开启

真实采集会调用已运行的 API/Worker 和 embedding/LLM，消耗 token 并产生费用。它不会启动服务。先配置同一个专用 `eval-` 租户下的 operator/approver 账号，以及 `SUPPORT_EVAL_OPERATOR_USERNAME/PASSWORD`、`SUPPORT_EVAL_APPROVER_USERNAME/PASSWORD`。只允许在已迁移的专用演示数据库中运行，它会为每条 case 创建独立知识库、业务对象和模拟 CRM 状态，并保留证据供检查。

```bash
docker compose -f compose.support.yaml exec api support-eval \
  --live-url http://api:8000 --permit-model-calls --output /tmp/support-live-eval.json
```

结果仍要求检查：LLM timeout 场景需要独立授权的故障注入 harness，采集器不会增加可公开调用的故障 API，也不会将未注入的失败当作已验证。embedding/fixture 成本尚未计量，因此 E2E 总费用保持未知；明确配置的单价只用于 chat-generation 费用，不混成完整运行费用。

Langfuse 默认关闭。开启 `SUPPORT_APP_TRACING_ENABLED=true` 并提供 Langfuse host/public/secret key 后，适配器按 run/thread/ticket 关联 Graph node、LLM、retrieval、CRM、approval 和 run status。只发送步骤名、身份关联 ID、计量值和结构化状态，不发送原始 prompt、客户文本或工具输出。Token 用量缺失或恢复过程中计量不完整时保持未知；LangSmith 自动 tracing 始终关闭。

## 验收证据边界

已可本地复现：30 条离线 Graph case、W20 的 20 并发测试替身与 15 条宿主安全回归、审批批准/拒绝/修改、checkpoint 回放、DB/Redis/旧 Worker 故障控制流、类型/编译检查、迁移 SQL 与 Compose 配置检查。

尚未证明：真实模型 E2E 成功率、人工引用正确率、完整成本和线上延迟、真实 PostgreSQL/Redis 崩溃恢复、Langfuse 服务端 trace、Docker 镜像构建与干净环境部署、浏览器端到端。这些证据不能由本地测试替身或 Compose YAML 的存在替代。

## 15 分钟展示提纲与技能矩阵

| 时间 | 内容 | 可展示的材料 |
|---|---|---|
| 0–2 分钟 | 工单场景、风险和系统边界 | `/support` 与架构图；页面需另行启动 |
| 2–5 分钟 | ticket/run/thread、队列与持久事件 | contracts、schema、API/outbox |
| 5–8 分钟 | 审批修订、幂等、取消与恢复 | 三条离线 Graph 路径与 W20 recovery tests |
| 8–11 分钟 | retrieval、引用、E2E 分层和失败归因 | 30-case 报告和独立 W19/W18 指标 |
| 11–13 分钟 | 两个局部改进与负向实验 | 单变量 JSON 对照；费用缺失保持未知 |
| 13–15 分钟 | 安全、部署和剩余实测 | 宿主安全用例、Compose、验收边界 |

| 能力 | 当前实现 | 证据范围 |
|---|---|---|
| LangGraph / HITL | typed state、interrupt、checkpoint、revise | 本地真实 Graph + 替身；PostgreSQL 待实测 |
| 企业 RAG | 版本化入库、pgvector/FTS、RRF、EvidenceRef | 代码与离线契约；真实召回待实测 |
| 后端运行 | FastAPI、Celery、outbox、lease、SSE | 本地 ASGI/控制流；分布式恢复待实测 |
| 安全 | RBAC、服务端租户、工具策略、审批、脱敏 | 15 条固定宿主回归；真实模型注入待实测 |
| 前端 | React、TanStack Query、时间线与回放 | 类型、lint、相邻测试；浏览器待实测 |
| Eval / 观测 | 冻结 case、归因、Langfuse、量纲分离 | 离线报告/回调替身；服务端观测待实测 |
| 交付 | Dockerfile、Compose、健康检查、离线 CI | 配置检查；构建、CI 远端运行与部署待实测 |
