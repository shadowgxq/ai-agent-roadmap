# AI Agent 通用模板：技术设计与实现规范

> 修订日期：2026-09-16。本文是后续实现规范，不代表代码已经实现或通过运行验收。
> 配套文档：[AI 公司研究：业务架构与接入设计](AI公司研究_业务架构与接入设计_v1.0.md)。
> 本文负责通用执行能力；公司、证券、财务、研究评级和报告章节由业务文档定义。

## 1. 实现目标与边界

在当前仓库设计独立的 agent-template/，提供可复用的 agent_core Python 包；research-agent/ 是第一个业务接入者。两个包使用本地显式依赖与锁定版本，不互相复制 Runtime，也不直接 import 三个教程项目的内部包。

公共模板是薄的运行基础，第一阶段服务一条固定业务图。动态规划、多 Agent、跨运行记忆都是按需扩展项，不能成为首份业务产物的前置阻塞。

| 公共模板负责 | 业务模块负责 |
|---|---|
| Run 生命周期、版本冻结、状态查询与恢复入口 | 业务请求、输出 schema、领域对象 |
| 外部操作台账、预算、有限重试、未知结果处理 | 搜索问题、来源规则、领域计算、具体错误解释 |
| Checkpointer、不可变产物接口、通用完成门禁 | 业务图、章节、评分、完整与降级准出规则 |
| 模型/工具端口、权限和上下文边界 | 业务工具实现、适配器能力要求、方法 Skill |
| 事件协议、Langfuse 适配与脱敏 | 可公开展示的业务进度与发现 |
| 上下文容量、工具调用协议、评估契约 | 受保护的业务上下文、用例、事实判定与质量阈值 |
| 可选 Plan/Worker 基础契约 | 是否规划、如何拆分角色、哪些阶段并行 |

不在本轮实现前端、HTTP API、任务队列、部署平台、插件市场或自动交易。文中的目录和接口均为设计，不在此次文档维护中创建代码。

## 2. 从当前教程提取的经验

以下结论来自当前教程和源码阅读，属于可借鉴的设计及已存在的代码形态，不是本轮运行证明。路径相对于仓库根目录。

| 教程与实际文件 | 提取的经验 | 封装后的责任 |
|---|---|---|
| weeks/W14.md；support-agent/src/support_agent/services/events.py | 内部框架事件转换成稳定应用事件 | EventProjector；不让消费方绑定 LangGraph 原始字段 |
| weeks/W15.md；support-agent/src/support_agent/persistence/checkpointer.py | Saver 生命周期、初始化与运行分离 | CheckpointerFactory |
| support-agent/src/support_agent/services/runner.py | start、inspect、continue、Command(resume) 区分 | Runner；额外补终态、版本、重复回答检查 |
| support-agent/src/support_agent/persistence/tool_actions.py、crm.py | 唯一键、事务、原请求匹配，审批与执行分离 | OperationLedger 与 AuthorizationRecord |
| weeks/W16.md；advanced-coding-agent/src/advanced_coding_agent/planning/langchain_planner.py | 结构化计划之后还需领域校验 | 可选 PlanValidator |
| weeks/W17.md；advanced-coding-agent/src/advanced_coding_agent/long_horizon/ | Goal、Progress、Context、Recovery、Completion 分层 | 冻结成功标准、小状态、分类恢复与完成门禁 |
| weeks/W18.md；advanced-coding-agent/src/advanced_coding_agent/multi_agent/ | 最小上下文、任务/尝试身份、依赖并行、保留冲突 | 可选 WorkerContract 与 ResultAggregator |
| agent-mini/src/agent/runtime.py、loop.py、cost.py | 模型调用观测、关闭隐式重试、用量估算 | ModelPort、ObservabilityPort、UsageRecord |
| agent-mini/src/agent/checkpoint.py | 原子保存产物的思路 | ArtifactStore；不引入第二套图恢复事实源 |
| weeks/W02.md、W03.md；agent-mini/src/agent/context.py、tools/registry.py | 工具参数校验、调用与结果配对、有限循环 | ModelTurn、ToolDispatcher 与图内有界工具子流程 |
| weeks/W07.md；agent-mini/src/agent/compact.py、rag/ | 保护目标的摘要、完整轮次裁剪、检索定位 | ContextPolicy；RetrieverPort 按需接入 |
| weeks/W08.md；agent-mini/src/tools/mcp_client.py | MCP 会话清理、工具命名空间、资源限制 | 可选 MCPAdapter，接入同一工具权限与操作台账 |
| weeks/W04.md、W09.md；agent-mini/evals/ | 客观断言、Judge、失败分类及版本对比 | EvalCase / EvalResult 与独立评估入口 |
| weeks/W05.md、W10.md；agent-mini/src/workflows/router.py、agent/cache.py | 结构化路由、路由自身费用、缓存用量 | 可选 ModelRoutingPolicy / PromptCachePolicy |
| weeks/W15.md；support-agent/src/support_agent/ticket_store_cli.py | 用户命名空间与 thread checkpoint 分离 | 可选 MemoryStore；不把偏好当成领域证据 |
| weeks/W19.md–W23.md | 知识版本、任务宿主、作用域、E2E 质量闭环 | 作为扩展设计输入；这些路线图内容不构成已实现或运行验收证明 |

需要修正后再借鉴的地方：

1. 当前 planning/graph.py 的实例属性 self.planner 与 planner() 节点方法同名。新模板用 planner_service / plan_node 分名；本轮不修改教程代码。
2. InMemorySaver 不能提供跨进程恢复；内存 Store 也不能作为业务证据仓库。
3. 本地模拟 CRM 与台账同库事务，只能说明该本地事务的幂等模式，不能推导远端模型或搜索请求只计费一次。
4. 当前事件适配器每次流读取从 sequence=0 开始。新模板需要持久化的运行内序号，不能直接把它当作可断线续读的事件日志。
5. 当前 Multi-Agent 的线程池超时无法杀死线程；新模板优先用 LangGraph 子图调度，不再叠加第二个任务调度器。
6. 成本估算发生在调用之后，不能替代调用前预算预留。当前 Langfuse 接入也需补全异常隔离与外发脱敏。
7. W07 的累计 input_tokens 表述不能用作当前上下文大小；loop.py 使用最近一次上下文用量也还需计入新增消息、工具 schema 和输出预留。新模板估算下一次实际请求，不照搬固定 70% 阈值。
8. cache.py 的供应商参数不能作为所有兼容接口的通用承诺；路由失败也不能无条件切换到更贵或未授权的模型。
9. agent-mini 的 AST 切片与本地向量索引面向代码定位。文档切片、页码、表格和证据可靠性由业务定义，不能直接套到财报。

## 3. 技术选型与代码依赖

| 能力 | 实现选择 | 边界 |
|---|---|---|
| 运行环境 | Python 3.12+，独立依赖声明和锁文件 | 实现时锁定实际兼容组合，不宣称范围依赖已验证 |
| 编排 | LangGraph StateGraph | 唯一的阶段、分支、子图与恢复编排器 |
| 模型接口 | LangChain + Pydantic 边界 schema | 结构合法不代表事实正确 |
| 原生服务端工具 | 独立供应商适配器 | LangChain 丢失必要协议字段时，适配器内允许使用官方 SDK/HTTP |
| 持久化 | PostgreSQL Checkpointer + 应用表 | 不操作 Checkpointer 内部表来维护业务数据 |
| 产物 | PostgreSQL 元数据，小响应入库，大文档用内容存储 | 先持久化正文，再登记可引用对象 |
| 观测 | 结构化事件 + Langfuse / Noop 适配 | 观测故障不破坏业务事实 |
| 计算、权限、预算 | 确定性 Python 实现 | 不执行模型生成的任意表达式或 callable |

~~~~text
research_agent → agent_core 公共契约
agent_core → LangGraph / LangChain / 持久化及观测适配
agent_core 不依赖 research_agent，也不识别公司或证券字段
~~~~

第一阶段不要求使用节点 timeout/error_handler 新参数。若使用，官方文档要求 LangGraph >=1.2；具体补丁版、集成包和 Saver 版本仍需锁定后验收。[LangGraph 容错文档](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)

## 4. 执行方式与协作方式分开

固定流程和动态计划是一条轴，单角色和团队是另一条轴，不能把 Plan 与 Multi-Agent 当成互斥模式。

| 配置轴 | 取值 | 使用条件 |
|---|---|---|
| workflow_kind | fixed / planned | 阶段已知用 fixed；步骤需随任务生成才用 planned |
| collaboration_kind | single / team | 单上下文足够用 single；有独立研究/权限/验证价值才拆分 |
| execution_profile | 业务登记的配置 ID | 冻结阶段、成功标准、能力、预算和工具 |

一次分类或问答可表示为单节点 fixed 图；标准研究是多阶段 fixed + single；四角色研究可以是 fixed + team。多步骤本身不是强制引入 LLM Planner 的理由。

### 4.1 固定工作流基线

~~~~text
冻结请求与版本 → 能力检查 → 业务阶段/局部补充
  → 产物校验 → 完成门禁 → 持久化结果
~~~~

阶段内部允许有限查询改写、结构化抽取和定向补充，所有循环都有上限、退出状态及产物身份。模型不能改变已批准范围与预算。

### 4.2 可选动态规划

Plan 至少含 goal_ref、plan_version、steps、dependencies、allowed_tools、success_criteria。代码校验依赖存在、无环、能力可用、预算可承担。

StepResult 保存状态、输入版本、产物引用、验证结果。Replan 创建新 plan_version，保留旧历史；只复用输入和验证仍有效的完成步骤，不能要求所有旧证据的 plan_version 必须等于新版本。

结束条件来自冻结的 Goal，不来自模型一句“完成”，也不来自最后一步成功。计划与重规划只提出任务，不在同一个规划节点偷偷执行外部工具。

### 4.3 可选团队协作

LangGraph 负责实际调度；公共模板只封装角色输入、权限、预算、任务身份和结果接受规则。独立 Worker 使用独立上下文，不广播全部 messages。

固定分支各写独立 result_ref，再显式汇合；动态分支保存 expected_task_ids，按 task_id + task_attempt_id 收齐。汇合不依赖返回顺序，旧尝试不能覆盖当前尝试。

对同一外部目标的共享写入指定唯一责任者；Worker 可以通过仓库接口追加自己命名空间内的不可变证据，不需要把“保存研究结果”错误地集中到一个 Coder。

## 5. 公共数据契约

本节字段是项目协议，不是第三方框架自带字段。所有外部边界做 schema 校验；时间为带时区 ISO 8601；金额/费用为十进制字符串；未知用 null，不能填零。

### 5.1 RunManifest

| 字段组 | 必须保存 |
|---|---|
| 身份 | run_id、request_id、request_hash、thread_id、parent_run_id |
| 配置 | workflow_id、workflow_version、graph_version、schema_version、execution_profile |
| 目标 | goal_ref、goal_version、completion_policy_ref/hash |
| 方法 | skill_id/version/hash、policy_bundle_ref/hash |
| 模型 | provider、endpoint_id、requested_model、adapter_version、capability_profile_ref |
| 执行策略 | context_policy_ref/hash、tool_loop_policy_ref/hash；启用时保存 routing/cache/retrieval/memory policy 引用 |
| 时间 | created_at、frozen_input_ref、deadline_at、已消费活跃时长 |
| 授权 | authorization_ref、budget_policy_ref、允许的供应商与工具 |
| 访问范围 | execution_scope_ref/hash，由可信宿主提供；本地单用户也有固定 scope_id |
| 复现 | dependency_lock_ref/hash、配置快照引用；不含凭证 |

实际 selected_model、returned_model、provider_request_id 写入每次交换/响应记录。单模型时使用上表默认值；启用路由时还需冻结候选集合及路由策略。endpoint_id 是可信配置标识，不接受网页指定的任意接口地址。

业务时间截点等领域字段保存在冻结业务请求，Runtime 不解释其含义。冻结内容必须保存可读取副本，只有 hash 而没有正文无法恢复。

### 5.2 Task、Attempt、Operation

| 标识 | 含义 | 何时变化 |
|---|---|---|
| task_id | 一个逻辑业务任务 | 任务目标/输入版本改变时新建 |
| task_attempt_id | Worker 执行该任务的一次尝试 | 改派、重做时新建 |
| operation_id | 一次冻结的外部交换 | payload、续接序号或授权重发交换改变时新建 |
| operation_attempt_id | 对同一交换的一次实际传输尝试 | 确定未发送后的安全传输重试时新建 |
| artifact_id / content_hash | 一个不可变产物及内容身份 | 内容变化产生新产物 |
| checkpoint_id | 一次图快照 | 由 Checkpointer 管理 |

推荐 operation_id 由 run_id、task_id、task_attempt_id、node_id、exchange_seq、canonical_payload_hash、adapter_version 确定性生成；序号在 prepare 节点冻结。普通节点重放沿用原身份，不因为重入生成随机 ID。

哈希采用有 schema/version 的规范 JSON、稳定键序、明确日期与 Decimal 表达。相同键但 payload 不同必须报冲突。

### 5.3 小状态和不可变产物

图公共状态仅保存 run_id、manifest_ref、phase、目标/计划/当前任务引用、业务结果引用、中断引用及循环计数。客户端、密钥、全文、原始响应不进入 state。

ArtifactEnvelope 包含 artifact_id、kind、schema_version、content_hash、storage_ref、created_by_run、created_by_task_attempt、input_refs/hashes、created_at。业务可扩展 payload，公共层只管理存取与依赖，不解释金融字段。

EvidenceRef 只定义 artifact_id、locator、摘要引用和 provenance_ref。业务负责证据是否可靠；公共 Runtime 不自称证据已真实核验。

### 5.4 状态分层

| 层 | 状态 | 权威来源 |
|---|---|---|
| 执行 | created / running / interrupted / failed_retryable / failed_terminal / completed / cancelled | Runner 综合 checkpoint、运行记录、操作台账 |
| 门禁 | pass / fail / review | CompletionResult 的逐项检查 |
| 业务结果 | 业务 schema 定义；如 complete / partial / blocked | 业务产物与交付清单 |
| 外部请求 | prepared / in_flight / response_stored / unknown / abandoned | OperationLedger |

completed 表示本次流程合法结束，可以交付降级或阻断说明，不等于完整业务目标达成。运行异常不能包装成 completed；next 为空也不能单独证明成功。

CompletionResult 分别保存 goal_verdict（目标是否完整达到）与 delivery_verdict（当前产物是否允许交付），二者取 pass/fail/review；逐项记录 criterion_id、check_type、status、evidence_refs、reason、policy_hash。完整目标未达到但降级交付规则通过时，可以completed + partial，不能宣称goal成功。delivery_verdict未通过时只能继续修订、等待复核或交付独立阻断说明，不能发布当前候选。任何事实错误、伪造引用或不可复算数字都不能靠标记partial放行。

## 6. Runner 接口与状态转换

均为 Python 层接口，不定义 HTTP 路由，也不隐含后台服务。

| 接口 | 语义 |
|---|---|
| start(request) → RunHandle | 幂等登记请求与冻结输入；不因创建句柄自动承诺后台执行 |
| advance(run_id) → RunSnapshot | 调用方持有运行锁，驱动新图直到暂停/终态/错误 |
| inspect(run_id) → RunSnapshot | 只读汇总图状态、当前阶段、操作未知项、产物、预算 |
| continue_run(run_id) → RunSnapshot | 推进未结束且不等待人工回答的原图 |
| resume(run_id, HumanResponse) → RunSnapshot | 回答指定中断，然后继续原图 |
| revise(parent_run_id, revision_request) → RunHandle | 已结束结果的修订，创建新 run/thread |
| cancel(run_id, reason) → RunSnapshot | 记录取消意图并协作停止；不声称撤销远端请求 |
| read_events(run_id, after_sequence) | 读取已持久化事件，不驱动图执行 |

第一阶段由本地调用方先 start 再 await advance；不额外引入队列。

合法转换为 created→running；running→interrupted/failed_retryable/failed_terminal/completed/cancelled；interrupted经有效回答回running，failed_retryable经恢复检查回running。completed/cancelled/failed_terminal不原位重开，需要新run。供应商paused仍是running；unknown需要人决定时为interrupted，无可继续动作则按业务规则交付阻断说明。

### 6.1 请求幂等

幂等比较限定在可信 ExecutionScope 的 scope_id 内；不同 scope 的相同 request_id 不互相返回运行结果。

1. 先对调用方原始请求的规范形式计算 request_hash，再填充默认时钟等值。
2. 数据库 request_id 唯一。同 ID 同内容返回已有 run；不同内容报 request_conflict。
3. 首次登记在一个事务保存 request、manifest、冻结初始输入和 run 记录。
4. 尚无 checkpoint：用原冻结输入启动；已有 checkpoint：按继续/中断状态处理。
5. 已结束：返回已有结果，不重新执行。

### 6.2 继续与人工恢复

故障恢复与人工恢复必须分开。人工问题由 prepare_question 固定后落盘，await_answer 节点只等待和检查回答，不搜索或扣费。

HumanResponse 保存 answer_id、run_id、interrupt_id、question_version、expected_checkpoint_id、answer、actor_ref、content_hash。重复 answer_id 同内容幂等返回；内容不同或问题已变化拒绝。

回答先登记为 pending，成功消费后标 applied。若回答已经入库但 graph 尚未推进就崩溃，恢复根据同一等待中的 interrupt 和 pending answer 继续提交；不能把“回答已存在”误判成“已经执行完”。同一中断不接受两个冲突回答。

图中保留 consumed_answer_id。若checkpoint已记录消费、回答表尚未标applied就退出，恢复只补回答状态，不再向已经前移的图重复提交。输入校验可重新要求有效回答，但不得覆盖已采纳决定。

同 thread 使用 Command(resume=...)；恢复会从中断节点开头重执行，GraphInterrupt 必须向框架传播。[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

### 6.3 修订与取消

revise 新建 run/thread，保留 parent_run_id，重新检查复用产物的输入、schema、策略和时间有效性。已结束 partial 不靠普通 continue 补跑。

取消后停止发出新调用，正在进行的调用仍可能返回或计费。迟到响应可以入台账和结算，但不能修改已取消任务的正式结果。若未知费用存在，取消快照必须保留它。

## 7. 持久化、事务和恢复

### 7.1 三类存储

| 存储 | 内容 | 写入责任 |
|---|---|---|
| Checkpointer | 图状态、任务、中断及持久化节点写入 | LangGraph Saver |
| 应用 PostgreSQL 表 | run、操作/尝试、预算、回答、产物元数据、事件 | 公共 Repository |
| 内容存储 | 大文档、不可变文本、业务产物正文 | ArtifactStore |

第一阶段小型供应商原始响应保存在应用数据库，便于与响应状态和已知用量同事务登记；大型文件先原子落盘/写入内容存储，再事务登记 hash 与引用。正文写失败不能登记为可用。

最小应用约束：runs的(scope_id,request_id)唯一，thread_id全局唯一；operations的operation_id唯一；attempts的operation_attempt_id唯一且关联operation；reservations的(operation_attempt_id,budget_kind)唯一；answers的answer_id及(run_id,interrupt_id,question_version)唯一；events的event_id及(run_id,sequence)唯一。数据库约束保护并发事实，不只在Python里先查后写。读取全局 ID 仍须校验所属 scope，ID 难以猜测不等于访问授权。

允许产生未被引用的孤立正文；清理由保留策略处理。不得删除仍被报告、审计或活动 checkpoint 引用的产物。续接 opaque 数据只在受控存储保留，不进入普通日志。

### 7.2 Checkpointer 约定

默认 AsyncPostgresSaver，初始化时 await setup，图执行期间保持 saver 生命周期；业务迁移与 saver 自身迁移分开。

默认 durability=sync；这控制写入时机，不能令内存 Saver 变成重启可恢复存储。普通恢复使用原 thread，历史 checkpoint 回放需显式新建关联运行，避免污染正式执行史。[LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)

子图默认 per-invocation，继承父图 Checkpointer；固定角色显式输入输出映射，不共享跨运行私有记忆。[LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)

### 7.3 响应与 checkpoint 的先后

~~~~text
冻结 ExchangeSpec → checkpoint
  → 原子登记 attempt + 预算预留
  → 标 in_flight → 发出请求
  → 保存响应 + 标 response_stored + 结算已知用量（同一应用事务）
  → 返回 response_ref
  → LangGraph 写 checkpoint
~~~~

节点重放先查 operation_id：已有完整响应就复用，不重新调用供应商。响应尚未完整保存而请求可能已发送，标 unknown；预算进入 held_unknown。

原生响应成功落盘不等于业务操作成功。HTTP 200 里的工具失败仍是已保存响应，由纯解析阶段判断，不能反复读取同一失败响应冒充重试。

响应已知但费用未知时保留未知预留；不得为了完成数据库事务把费用写零。业务可按软预算政策交付已知结果，usage_summary 必须注明未结清项。

### 7.4 锁与并发

每次 advance/continue/resume 持有同一 run 的排他锁。第一阶段采用专用数据库连接持有会话级 advisory lock，进程内再防重复进入；仅 asyncio.Lock 不足以挡住第二个 CLI 进程。

锁连接丢失后停止新调用并隔离该运行，确认旧执行者已停止才能接管，不用自动过期租约假装完成强制终止。对迟到结果按 task_attempt_id 判定有效性。操作预留、预算和回答同时依赖数据库唯一约束与事务，锁不能替代这些约束。

### 7.5 必须覆盖的崩溃窗口

| 时点 | 恢复行为 |
|---|---|
| 请求已登记、首个 checkpoint 前退出 | 使用已保存初始输入，不刷新默认时间 |
| 预留后能证明尚未发送 | 安全释放或有限重试，记录新传输 attempt |
| 已标 in_flight 但发送事实不明 | unknown，保留预留，不根据本地标志推断未消费 |
| 远端已处理、响应未存 | 对账；无查询能力时按授权决定是否新交换重发 |
| 响应已存、checkpoint 未存 | 复用 response_ref，再推进图 |
| 候选产物已存、交付未登记 | 按确定性键复用产物和有效门禁结果 |
| 交付已登记、终态 checkpoint 未写 | 恢复时补引用/终态，不重复生成 |
| 一个并行分支失败 | 复用已持久化的成功分支；不保证找回未保存输出 |

Checkpoint 不与远端调用构成事务，不能保证远端费用或副作用 exactly-once。需要远端支持幂等或查询才能进一步缩小未知窗口。

## 8. 操作、重试与预算

### 8.1 OperationLedger 接口

prepare_exchange / reserve_attempt / mark_in_flight / store_response / mark_unknown / reconcile / get_existing_response。所有模型调用都经过该路径，包括规划、抽取、审稿、修复和原生搜索。

主要约束：

- operation_id 唯一且绑定 payload_hash。
- operation_attempt_id 唯一；预留键为 attempt_id + budget_kind。
- 同一操作最多接受一个正式响应；重复内容幂等，冲突内容进入隔离。
- 业务结果接受与费用结算分开；过期结果被拒收也可能需要结算。
- parse/normalize 是可重放的纯处理；解析器变化产生新的解析产物版本。

### 8.2 唯一重发入口

关闭 SDK 未计账的自动重试，由公共 RecoveryPolicy 负责。LangGraph RetryPolicy 仅用于明确无远端消费风险的已分类瞬时故障，不能再包一层通用三次重试。

| 情况 | 处理 |
|---|---|
| 确定未发出的短暂连接故障 | 同 exchange，最多首次加两次传输重试 |
| 收到明确可重试 429/5xx | 保存响应，遵守供应商重试语义和 Retry-After；新 exchange |
| HTTP 成功但工具失败 | 解析工具错误，有限创建新 exchange，不复用错误缓存作为成功 |
| 发送后读取超时、远端结果未知 | reconcile；没有事先授权不自动重发付费请求 |
| schema 无效 | 先纯解析修复；必要时至多一次受计账模型修复 |
| 搜索空结果 | 业务缺口与有限改写，不当网络失败 |
| 401/403、参数错误、权限不足 | 阻断配置，不重试相同错误输入 |
| 数据库/证据持久化失败 | 停止推进及新付费调用；恢复前重查事务结果 |
| 未知程序异常 | 失败并保留诊断，不能降级为“资料不足” |
| 人工中断或供应商续接 | 各自正常控制流，不计入普通失败重试 |

幂等只读不代表免费：付费搜索即使不改外部数据，超时也必须考虑重复消费。

### 8.3 BudgetPolicy

预算统一覆盖身份查询、能力探测、正文抽取、生成、审稿、修复、续接、重试。每次发出前原子预留，已知消费结算，未知消费继续占用。

~~~~text
hard 模式：已结算费用 + 全部未结算预留 ≤ 已批准额度
前提：每次调用可证明费用上界，并按该上界预留
~~~~

若供应商内部搜索次数或计费没有可验证上界，只能提供软预算：达到阈值停止后续调用，不能承诺已发请求绝不超额。请求 hard 而能力不足时启动前阻断。

BudgetPolicy 必须定义请求数、输出 token 上限、总/单阶段时间、重试/续接/补充/修订上限、cost_limit_mode、cost_limit、unknown_replay_policy。未配置不能悄悄视为无限。

预算保存计价币种、价格表版本/生效日、供应商计费项及可适用汇率；估算费用、供应商返回用量和最终账单不得混成一个已确认金额。hard模式预留必须包含所有可计费项；没有完整价格上界不能只靠token估算宣称封顶。

并行预算使用数据库原子预留；费用按台账去重汇总，不能由 state reducer 直接累加扣费。统计真实内部工具次数和应用请求批次时分栏，未知次数不用 0。

### 8.4 时间边界

连接/读取超时、单次交换期限、Run 总期限和人工等待期限分别定义并持久化。恢复不重置已消耗时间。取消 await 或线程超时，不代表远端已停止。

## 9. 模型、工具、Skill 和上下文接口

### 9.1 必要端口

| 端口 | 公共契约 |
|---|---|
| ModelPort | invoke_once(exchange_spec) → ModelTurnRef；invoke_structured 在其上完成 schema 校验，额外修复调用必须显式入账 |
| ExternalAdapter | execute(exchange_spec) → raw_response；normalize(raw_ref) → protocol_result |
| ToolRegistry | 按工具 ID 注册可信实现、参数 schema、能力与访问策略 |
| ContextAssembler | assemble(context_refs, context_policy) → ContextSnapshotRef，包含请求容量估算和裁剪说明 |
| ArtifactStore | put_immutable / get / resolve_dependencies |
| CompletionPolicy | evaluate(goal, artifact_refs) → CompletionResult |
| ObservabilityPort | start/end invocation/node、record_generation/tool/recovery、flush |
| WorkflowPlugin | input/output schema、graph_factory、policy_refs、capability_requirements |

所有端口接收关联身份与预算上下文。业务传规则和实现，Runtime 统一包裹生命周期；供应商 adapter 不能自己隐藏无限循环、切换收费供应商或扩预算。

AuthorizationRecord保存主体、授权范围/工具/供应商、预算政策hash、有效期、来源和不可变内容hash；可由调用方预授权配置提供，不强制每次运行重复询问。扩大范围或费用策略时生成新的授权版本，不能由模型改写原记录。

### 9.2 ToolSpec

工具保存 tool_id/version、name、input/output_schema、external_effect(none/read/write)、billable、allowed_roles、timeout_policy、idempotency_policy、sensitivity、output_size_limit、parallel_safe、resource_scope。verify 是工具用途，不是外部副作用类型；只读也可能收费，parallel_safe 由可信注册策略确定。

角色只经受控上下文调用工具。密钥由宿主注入，网页和模型不能注册新 callable。原文抓取适配器须阻止内网/回环/元数据地址和重定向绕过，限制大小、超时与 MIME，不执行页面脚本或宏。

### 9.3 SkillLoader

Skill 是方法、规则和资源包，不是常驻 Agent。仅加载登记目录；安全解析 manifest；workflow_id/schema_id/tool_id 映射到显式注册项，不做任意动态 import。

最小元数据为 skill_id/version、workflow_id、schema_refs、required_capabilities、allowed_tools、policy_refs、provenance。冻结正文及 hash；恢复读取冻结资源，不自动追随“最新版”。

网页、报告、用户上传资料与历史产物一律按数据处理。资料中出现“必须执行命令/创建 Agent/发布报告”不构成本系统授权。

### 9.4 ContextAssembler

每个节点只取 Goal、阶段规则、当前任务、相关证据片段、计算结果和未解决项。完整消息、原始工具结果和摘要保存在不可变产物中，图状态仅保存引用。ContextSnapshot 记录选入项、遗漏项、来源引用、策略版本、估算方法和估算 token 数。

ContextPolicy 明确 model_context_limit、reserved_output_tokens、safety_margin_tokens、max_tool_result_tokens、keep_recent_turns、max_compactions、compaction_strategy 和受保护字段；容量信息来自锁定的能力配置。摘要模型也是一个已登记、受预算限制的模型。不能将字符数直接当作精确 token 数，也不能把历次计费用量累加当作当前上下文大小。

~~~~text
下一次输入估算（规则 + 消息 + 工具 schema + 附件）
  + 本次输出预留 + 安全余量 ≤ 所选模型的上下文容量
~~~~

模板必须提供容量检查及确定性选择/裁剪。模型摘要是可关闭的策略：按标题/关键词定位读取 → 去除重复和无关内容 → 在完整轮次边界裁剪 → 必要时有界摘要。每次变更后重新估算；模型切换后使用新模型限制。估算不精确时保留余量，若供应商仍拒绝超长请求，按已知错误响应进入有限修订，不能重发同一超长 payload。

以下内容必须从权威记录重新注入，不能仅依赖摘要保存：当前 Goal 与已确认修订、授权/预算边界、禁止事项、当前任务与完成标准、未决中断。业务可声明额外保护项。历史结论、冲突与关键证据引用应保留；摘要属于派生产物，不能升级为事实来源，也不能覆盖原始请求。

客户端工具的 call/result 按完整配对单元保留或移出当前上下文；尚未得到确定结果的调用先完成恢复处理。供应商 opaque 续接块按其协议处理，不能随意摘要、改写或迁移。不同模型的角色/消息格式由适配器校验，不强制沿用教程中某一家接口的消息格式。[LangChain 短期上下文约束](https://docs.langchain.com/oss/python/langchain/short-term-memory)

摘要先持久化正文、输入引用和策略 hash，再更新 ContextSnapshot 引用。恢复时复用已保存摘要；摘要调用及其重试同样经过 OperationLedger。失败后只能在不丢保护项的前提下做确定性裁剪；仍超限则返回 context_limit 阻断原因，不能悄悄删除目标或继续无界压缩。

第一阶段使用标题、关键词和定位读取；RAG、长期 Store、向量库不作为必需依赖。跨 run 复用依赖业务有效性检查，不用旧聊天记忆替代证据。

### 9.5 有界模型与工具循环

一次 ModelPort 调用只负责一个冻结的模型交换，已存响应直接复用，传输重试遵循第 8 节；返回规范化 ModelTurn：文本/结构化候选引用、client_tool_calls、stop_reason、usage_ref、raw_response_ref 及可选 continuation_ref。refusal、输出截断、待工具结果、供应商暂停必须区分；没有 tool_call 不代表业务完成。

只在业务需要客户端工具选择时启用 LangGraph 内的工具子流程；每轮模型与工具结果都有 checkpoint/操作引用，不在一个普通节点内部藏无限 while，也不另造调度器。原生服务端搜索由供应商适配器解析，不能把其内部工具记录再次派发为客户端请求。

1. 发出请求前完成上下文、权限、预算和剩余轮数检查；流式参数必须收齐并校验后才能执行。
2. 按冻结工具表解析 tool_id、参数 schema 和资源范围；参数合法仍需通过授权检查。未登记工具、超范围路径/URL、无效参数不能进入执行器。
3. 每个 tool_call 以父模型 operation_id + provider_call_id 建立稳定映射，再登记自己的操作身份。模型输出相同函数和参数不自动代表同一次外部操作；也不能只按参数 hash 跨 run 复用副作用。
4. 仅对显式 parallel_safe 且互不依赖的调用并行，受并发及预算限制；共享目标写入串行。结果按原调用 ID/顺序组装，异步完成顺序不影响下一轮消息。
5. 每个调用产生唯一已登记结果：success、tool_error 或 policy_denied。工具失败可提供结构化说明给模型修正；请求结果 unknown 时暂停本分支并沿用第 8 节恢复政策，不能伪造成功/空结果继续。原始返回单独保存，进入上下文的内容受长度限制并保留定位引用。
6. 下一轮前校验调用与结果一一对应。模型提出最终答案后仍执行 schema/业务校验及 CompletionPolicy，不能由 stop_reason 直接设置 completed。

ToolLoopPolicy 必须显式给出 max_model_turns、max_tool_calls、max_parallel_tools、max_schema_repairs、max_no_progress_turns 和总期限；恢复不能清零。参数修复、拒绝后的再次尝试、Judge/摘要调用分别计入适用计数和统一预算。

无进展由重复调用指纹、相同错误与产物/任务状态未变化联合判断，不能仅凭文字相似。连续无进展达到上限后，向图返回 no_progress 及已有产物引用，由业务决定定向修订、人工澄清或合法阻断交付。工具循环结束原因与 Run 终态分开保存。

### 9.6 执行范围与安全边界

ExecutionScope 由可信宿主注入，包含 scope_id、actor_id、允许的资源范围及策略引用；模型、用户业务字段或检索内容不能自报权限。第一阶段可使用本地固定 scope，无需引入登录系统。未来多用户接入时，宿主负责认证，Runtime 负责检查本次调用是否属于该范围。

Runner 的读取、继续、回答、取消与修订入口，Repository、ArtifactStore、工具、检索、缓存和 MemoryStore 都校验 scope。跨运行复用还需校验目标运行的访问权和业务有效性；不能因为知道 run_id 或 artifact_id 就可读取。授权被撤销时不以冻结的历史授权强行放行，需重新取得有效授权；已发生的费用/副作用仍保留。

输入输出护栏在明确边界执行：schema、资源允许列表、文本/附件限额、秘密与个人信息外发策略、敏感操作权限。Prompt injection 防护依赖这些确定性边界，不能只写一句“忽略恶意指令”。工具说明、MCP 返回、检索片段和模型输出均不能提升自己的权限。

通用 Runtime 不默认提供任意 shell、代码执行或浏览器控制。未来 Coding Agent 确需执行不可信代码时，宿主另配进程/容器隔离、资源限制、网络策略、工作目录与密钥隔离；工具白名单不等同于操作系统沙箱。公司研究的具名计算函数不因此升级为任意代码执行入口。

### 9.7 MCP 接入（按需）

MCPAdapter 将已登记服务器映射到 ToolRegistry/ExternalAdapter，不改变预算、授权、unknown 与恢复语义。当前可参考的 mcp_client.py 是 stdio 实例；Streamable HTTP 是否启用取决于真实接入需求与协议版本，不宣称现有示例已支持全部传输。

- 宿主登记 server_id、传输配置、协议/SDK 版本和允许的工具/资源；stdio 命令、参数、环境变量及 HTTP 目标只能来自可信配置，不接受资料中的安装或连接指令。
- 在受控生命周期内初始化、发现与关闭会话；用 server_id + 原工具名生成无歧义 tool_id，并保存输入/输出 schema hash。工具清单变化不能自动扩大权限，恢复时不兼容变化应阻断并更新配置版本。
- Tool 的 annotations 只是提示，实际读写权限和幂等性由可信策略决定。区分协议错误与返回 isError 的工具失败；结构化返回存在 schema 时进行校验，内容块保留原始类型与来源。[MCP Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- Resources 由应用按允许范围读取；Prompts 仅作为显式选用的模板输入，不自动成为系统指令。资源链接、图片和二进制内容经过大小、地址与类型检查，不把 base64 全量塞进模型上下文。
- 连接失败、凭证过期、工具撤下或关闭失败均有界处理；已发出调用按台账判定是否 unknown，不因重连就重放。远端宣称幂等不作为唯一保证，能力和合同需登记。

本轮只定义接入规则，不启动 MCP 服务、安装插件或自动启用远端工具。

### 9.8 模型路由与缓存（按需）

默认单一模型能力配置。路由确有收益时，再按任务类型、所需 schema/工具/上下文能力、数据外发范围和预算选择候选；优先确定性配置，必要时使用一次受预算约束的结构化分类。ModelRoutingPolicy 冻结候选集合、选择规则、失败路径与升级条件，模型不能自行引入新供应商。

路由决定在交换 prepare 前持久化，随后冻结 selected_model、provider 和 capability_profile。恢复同一交换不重新路由；任何实际模型切换均创建新交换并重新校验上下文和预算。路由结果无效时使用已配置且已授权的候选，找不到满足约束的候选则阻断；不能总以“更强模型”作为无条件降级。

fallback 必须基于确定的失败事实，并遵守第 8 节 unknown 政策；客户端超时不能触发跨供应商重复付费。供应商 opaque continuation 不跨供应商复用。路由器本身、升级、补充和修复调用都要进入成本与质量对比。

| 缓存/复用类型 | 可以封装的内容 | 必须守住的边界 |
|---|---|---|
| 同一 operation 的持久响应复用 | 恢复时读取已经落库的响应 | 属于执行正确性，基础必需；不能用 TTL 将它误当作新请求 |
| Prompt caching | 模型供应商对稳定提示前缀的缓存 | 供应商能力适配，业务语义不变；不假定一定命中或免费 |
| 业务查询/结果缓存 | 可复用的文档抽取、检索或业务产物 | 默认关闭跨 run 复用；业务明确范围、数据版本、有效期和失效条件后启用 |

PromptCachePolicy 只暴露启用状态、命名空间与期望保留策略，适配器按真实能力翻译，不能将某家额外字段原样传给所有兼容接口。保持规则/工具 schema/Skill 的稳定前缀，动态请求放后部；不要为提高命中率漏掉权限、日期或必要证据。[供应商缓存机制示例](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

用量保留供应商原始口径，并明确普通输入、缓存读取、缓存写入之间是包含关系还是互斥项，避免重复相加。未知命中/费用不能填零；hard 预算不依赖未经保证的缓存优惠。效果比较须在相同用例下同时报告质量、延迟、总成本和缓存命中，不能只展示 token 降幅。

业务结果缓存键至少包含 scope、规范输入、workflow/schema/Skill/模型策略版本、数据快照与相关业务时间条件；scope 的包含不能替代读权限检查。过期、失效或缺少依赖版本时重新取得有效数据，不能把旧报告缓存当作今天的事实。

### 9.9 检索与长期记忆（按需）

RetrieverPort 的契约为 retrieve(query, corpus_snapshot_ref, access_scope, filters, limit) → RetrievalResultRef。结果含 source/artifact、chunk_id、定位、内容 hash、语料版本、检索器/embedding 版本和分数；分数仅用于排序，不代表来源可信或事实成立。

第一阶段由业务提供标题、关键词、页码/段落定位读取；只有文档规模和评估表明需要时才增加向量检索、全文检索、RRF 融合或 reranker。W19 的 pgvector + FTS 是可选后端，不是公共包的必需基础设施。

启用知识库后，接入契约需满足：

1. 业务负责文档解析、页码/表格定位和切片策略，公共层只接收标准引用；扫描件是否 OCR 由业务能力定义，不沿用代码 AST 或教程的禁用范围。
2. 完成解析、切片和索引后再发布完整 corpus_snapshot；查询固定一个版本，不混入半成品或不同 embedding 空间。更新、撤回与删除必须传播到索引和缓存。
3. 授权过滤在向量/全文各检索分支返回内容前生效；时间可见性等业务过滤也须两边一致。不能先跨范围召回，再让模型删除无权看的内容。
4. 无命中、索引不可用、低相关度和证据冲突分开返回；不能以模型常识补成“查到的证据”。嵌入、重排或查询若收费，同样受操作与预算约束。
5. 分别评估检索召回/排序、引用定位和答案证据支持，检索命中不能替代 CompletionPolicy 的事实门禁。

MemoryStore 保存跨 run 的用户偏好或明确批准复用的状态，与 thread checkpoint、知识库证据和产物缓存分开。命名空间至少含 scope_id + subject_id + memory_kind，记录来源、版本、生效/失效时间和写入政策；默认不从工具返回或模型推测中自动写入用户偏好。

当前请求和明确修订优先于旧偏好。读取记忆不能扩大工具/费用权限，也不能将旧研究结论当作新的领域事实。需要可查询、更正、过期与删除；删除后阻止未来检索和注入，历史不可变记录按独立访问/保留政策处理，不承诺删除一项记忆就擦除所有历史副本。

## 10. 事件与 Langfuse

### 10.1 稳定应用事件

~~~~text
event_id / run_id / invocation_id / sequence / occurred_at
event_type / node_id / task_id / task_attempt_id
status / safe_summary / artifact_refs / schema_version
~~~~

sequence 为运行内持久化、单调递增序号；唯一约束 (run_id, sequence)。重放相同已登记事件复用 event_id，不靠内存计数器去重。

阶段/产物转换与对应关键事件在同一应用事务登记；完成事件只能在交付对象已持久化之后产生。未持久化的观测 span 不冒充正式进度。消费方按序号续读并以 inspect 校准，不预设事件不重复或永不丢连接。

公共事件包括 run_started、phase_changed、task_finished、operation_unknown、human_input_required、completion_evaluated、run_finished；业务扩展 search_completed、conflict_detected 等。不得从文本流结束直接推导 run_completed。

### 10.2 观测实现

业务代码只依赖 ObservabilityPort。提供 LangfuseObservability 和 NoopObservability；在 Runner/模型/工具边界插桩，不要求业务节点逐个 import SDK。

一个 run 可以跨进程多次 invocation，每次建立自己的根 observation，以 run_id/thread_id 关联；不让一个活跃 span 跨进程或跨数天人工等待悬挂。子节点、模型与工具记录 task/operation 身份。

一次模型调用只选择一条 generation 采集路径：LangChain callback 或手工 SDK；禁止重复记录并将两份 usage 累加。预算事实始终来自调用台账。

Langfuse 初始化、update、导出及 flush 失败均有界降级到本地日志。Noop/导出失败要在观测状态可见，不能伪称 trace 上传成功；默认不因此阻断有效业务交付。

### 10.3 隐私与版本

默认只外发摘要、ID、hash、用量、状态；提示词、完整原文、原始响应、个人信息与凭证不默认外发。模型内部思考不记录。脱敏发生在外发前，Artifact 与 checkpoint 的访问/保留另行管理。

实现时锁定 Langfuse SDK 与服务端兼容版本。v4 的关联属性通过 propagate_attributes 传播，SDK span 过滤与 mask 只管对应导出路径，不能代替应用全局治理。[Langfuse v4 迁移](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)、[Masking](https://langfuse.com/docs/observability/features/masking)

## 11. 目录与最小实施批次

~~~~text
agent-template/
  pyproject.toml
  src/agent_core/
    contracts.py
    runner.py
    errors.py
    ports.py
    operations.py
    budgets.py
    persistence.py
    artifacts.py
    events.py
    observability.py
    skills.py
    context.py
    tools.py           工具注册、受控派发；循环由 LangGraph 编排
    access.py          本地 scope 与资源访问检查
    planning/          按需增加
    workers/           团队接入时增加
    adapters/          真实需要 MCP/检索/多供应商时再增加
  evals/               用例协议与评估入口；不进入生产运行链

research-agent/
  pyproject.toml       显式依赖本地 agent_core
  src/research_agent/  仅业务对象、图、工具与规则
  skills/             研究方法及 policy 资源
~~~~

先实现实际使用的文件，出现多个适配器或较大职责再拆目录；不预先创建空壳。公共包没有 company_id、security_id、DCF 或管理层评分的硬编码。

| 任务 | 责任模块 | 依赖 | 后续完成条件 |
|---|---|---|---|
| T0 契约和调用入口 | agent_core contracts/runner | 无 | 请求去重、冻结输入、状态分层、固定图注入 |
| T1 可恢复外部调用 | persistence/operations/budgets | T0 | 响应复用、unknown、事务、持久化恢复、单推进 |
| T2 上下文、工具与交付基础 | artifacts/events/observability/skills/context/tools/access | T0、T1 | 不可变依赖、事件续读、观测故障隔离、容量边界、工具配对、访问范围；定义 EvalCase/EvalResult |
| T3 首个业务接入 | research_agent 的 B0 + 业务 evals | T0–T2 | 按业务范围生成可追溯 P0 结果，建立确定性/录制样本基线；真实模型验收另按授权执行 |
| T4 团队扩展 | workers + 业务 B2 | T3、完整标准业务能力 | 私有上下文、显式汇合、预算并发、旧结果拒收 |
| T5 动态规划 | planning | 真实业务出现动态步骤需求 | Plan/Replan 不破坏固定图与既有恢复契约 |
| T6 外部协议接入 | adapters/mcp | T0–T2、真实工具需求 | 注册/生命周期/错误映射完整，不能绕开权限和台账 |
| T7 知识与记忆 | 可选 retrieval/memory 适配 + 业务入库 | T3、规模或跨 run 需求 | 知识快照、来源定位、权限、失效与删除；业务证据不混入用户偏好 |
| T8 成本与模型优化 | 可选 routing/cache 策略 | T3、可比较的评估基线 | 质量边界不退化，真实总成本/延迟可比较，降级路径可审计 |

T5–T8 不是 T3/T4 的统一前置；只有业务明确选用某能力时才成为该业务路径的依赖。T2 先完成上下文容量检查和确定性裁剪；模型摘要按需启用。Langfuse 端口与故障隔离在初期设计，不必等完整 Planner 之后才补。

## 12. 后续实现验收要求

本次未运行以下场景；它们是实现完成后需要证明的行为。

| 场景 | 必须看到的结果 |
|---|---|
| 同 scope 内同 request_id 连续开始、不同内容重用 | 前者同 run，后者明确冲突；不同 scope 不串用结果 |
| 首个 checkpoint 前退出 | 原输入与默认时间不变 |
| 已保存响应后退出 | 不再发请求，只推进引用 |
| 请求发送后超时 | unknown 与 held_unknown，不自动视为安全重试 |
| 已保存错误响应后重试 | 新 exchange 身份，不循环命中旧错误缓存 |
| 两个 CLI 继续同 run | 一次有效推进，无双重预算预留 |
| 回答登记后退出、重复回答 | 同一回答可继续消费且不二次应用；冲突回答拒绝 |
| 终态结果再 continue | 返回原结果；补充通过 revise 创建新 run |
| 取消后迟到响应 | 可结算台账，不能覆盖正式结果 |
| Langfuse 不可用 | 状态与业务产物仍正确，观测降级可见 |
| 关键持久化失败 | 停止推进，不降级到内存后声称可恢复 |
| 并行旧 attempt 迟到 | 不覆盖当前结果，不少算其费用 |
| Skill/图版本不兼容 | 拒绝原位恢复，显式迁移或关联新 run |
| 全步骤结束但成功条件不满足 | 完成门禁失败/待审，不能宣称目标达成 |
| 大工具结果使下一次请求超限 | 预留输出后裁剪/有界摘要，保护项与证据引用保留；仍超限则明确阻断 |
| 摘要已保存但 checkpoint 未更新 | 恢复时复用摘要，不重复收费；原始输入可追溯 |
| 部分工具参数流、缺失/重复 call ID | 不执行未校验调用，不发送未配对的下一轮消息 |
| 工具连续重复失败或无新产物 | 达到已冻结上限后结束子循环，不冒充目标完成 |
| 资料或工具返回要求越权 | 不能扩大 scope、注册工具、泄露秘密或写入长期偏好 |
| 启用 MCP 后清单/schema 变化 | 原授权不自动扩展，不兼容恢复明确阻断 |
| 路由/缓存优化 | 没有未授权 fallback；unknown 不自动重发造成重复消费，缓存费用口径不双计 |
| 启用检索/记忆后范围或版本变化 | 无越权召回、半成品索引、失效记忆注入或旧证据冒充新事实 |
| 评估样本或依赖变化 | 显式报告不可直接比较的部分；安全失败不被平均质量分掩盖 |

只有相应场景实际运行后才能称为运行验收；源码存在、文档完整、schema 合法都不能替代这项证据。

## 13. 跨版本评估与优化依据

CompletionPolicy 判断单次运行是否允许交付；Evals 判断某个实现、提示词或模型策略在一组固定用例上的表现。两者共享检查定义和证据格式，但 Evals 不作为每次生产运行额外执行的整套流程。

公共模板只封装用例协议、驱动入口、断言结果与对比格式。具体输入、事实标准、目标阈值及是否调用真实服务由业务提供；不能把 Coding Agent 的“测试通过/修改文件”作为研究 Agent 的通用成功标准。

### 13.1 最小评估契约

| 对象 | 必须保存 |
|---|---|
| EvalCase | case_id/version/hash、输入与 fixture 引用、允许工具/副作用、预算、客观断言、可选 rubric、失败标签、预期交付类型 |
| EvalExperiment | experiment_id、case_set_ref/hash、案例选择/重复次数、workflow/Skill/schema/策略/依赖版本、环境与供应商模式、Judge 配置、比较基线 |
| EvalResult | case_id、repeat_index、run_id、各断言 pass/fail/unknown、goal/delivery verdict、产物引用、失败阶段、usage/cost/latency、可选 Judge 分数及理由 |

每个 case/repeat 使用独立 run/thread 和隔离数据；恢复专项用例可在该次用例内部复用自己的 run。基线与候选共享冻结 fixture，不共享可变 checkpoint、预算或工具副作用。记录随机参数只能帮助解释差异，不能保证供应商完全确定性复现。

可使用 Langfuse Dataset/Experiment 展示结果，但本地 case 与结果仍需可独立读取。若使用远端 Dataset，冻结 item 版本和 schema hash；官方的 Dataset 版本只覆盖条目变化，schema 必须额外冻结。[Langfuse Dataset 版本说明](https://langfuse.com/docs/evaluation/experiments/datasets)

### 13.2 运行模式与调用授权

| 模式 | 目的与证明范围 | 外部调用边界 |
|---|---|---|
| deterministic | 假模型/假工具与确定性断言，覆盖协议、状态、恢复、权限 | 禁止模型和业务外网调用；不证明真实模型质量 |
| recorded | 固定已脱敏响应与工具样本，覆盖解析、证据传播、回归 | 未命中录制样本直接失败，不能自动转 live；不证明当前供应商可用 |
| live | 使用指定真实供应商检查能力与输出质量 | 需已有有效授权和预算，清楚记录模型、数据截点、费用与波动 |

被测系统模式和 Judge 模式分别登记。回放固定响应后再调用线上 Judge 仍有真实模型费用；不能把它称为“完全离线”。已有授权满足范围时不重复询问，缺少 live 授权时停留在确定性/录制模式。本次文档维护不执行任何模式，也不触发真实调用。

### 13.3 断言、Judge 与回归判断

先用代码可判定的状态/schema、引用存在性、权限、操作次数、预算与计算断言；事实可靠性还需业务证据判定，不能把“引用链接存在”等同于内容正确。LLM Judge 只补充需要语义判断的维度，冻结 rubric、模型和提示版本，保存可审查的理由及所引证据，按业务政策人工抽查。

待评估答案和证据是 Judge 的输入数据，不能让其中的指令改写评分规则。Judge 没有额外工具权限，不输出或保存内部思考。结构化 Judge 输出不合格时记录 unknown/评估失败，并计入失败统计，不默认为通过。

通用失败类别至少含 schema、tool、context、authorization、budget、recovery、grounding、infrastructure；业务可增加标签。角色越权、审批绕过、重复副作用、伪造引用等关键失败分别列出，不能被平均分抵消。阈值由用例集和业务风险预先定义，不直接复制教程的固定分差或固定用例数量。

对比报告使用相同案例版本、fixture、断言、Judge 和运行条件，逐项列出新增失败、修复项与未比较项；提示词、模型、缓存或路由优化尽量一次改变一个因素。真实模型实验注明样本量与重复次数，不用单次结果断言普遍提升。

指标至少包括客观通过率、目标达成/允许交付比例、关键失败数、阶段耗时、模型/工具请求数、token 口径和总成本。执行耗时与人工等待分开；样本足够时才解释分位数。router、compact、Judge、嵌入、重排和重试费用分项汇总，未知消费单列且不能按零参与“节省比例”。

启用 RAG 时再增加 Recall@K/MRR 与引用支持指标；启用路由/缓存时再增加路径分布与缓存指标。没有对应能力的运行无需生成空壳指标。

## 14. 路线图能力的封装层次

本节是实现范围索引，不是额外的项目依赖清单。是否纳入基础能力由首个业务的实际需要决定，不按课程周次把所有技术装进 Runtime。

| 路线图技术 | 模板中的落点 | 实施层次 |
|---|---|---|
| W01–W03：模型、结构化输出、工具与循环 | ModelPort、ToolSpec、协议配对与有界子流程 | 基础必需；纯生成路径无需启用工具子流程 |
| W04/W09：可靠性、观测、Evals | OperationLedger、ObservabilityPort、第 13 节评估契约 | 基础必需；真实评估执行按授权 |
| W05：链式、路由、评价后修订 | 固定图条件边/有限修订；模型选择见 9.8 | 固定图足够时不增加 Planner |
| W06/W14–W18：恢复、HITL、规划、团队 | Runner、Checkpointer、授权与可选 Plan/Worker | 恢复基础必需；规划/团队按需 |
| W07：Context Engineering、轻量检索 | ContextAssembler、保护项、容量检查与定位读取 | 基础必需；模型摘要可选 |
| W08：MCP | 第 9.7 节协议适配 | 真实工具接入时增加 |
| W10：缓存、模型分流、Guardrails | 第 9.6/9.8 节 | 权限与边界基础必需；性能优化按需 |
| W11–W12：Streaming、UI、执行环境 | 模型流组装与稳定应用事件；宿主 UI/沙箱 | 流不改变完成语义；UI/代码沙箱非首期公共模板范围 |
| W13：框架映射 | LangGraph 唯一编排与显式模型/工具适配 | 选定一条实现路径，不同时保留手写调度器 |
| W15 Store / W19 企业 RAG | 第 9.9 节的记忆与检索契约 | 需求触发后接入，持久化技术可替换 |
| W20–W22：服务化、队列、用户与工作台 | 下述宿主适配边界 | 不作为本地模板前置 |
| W23：E2E 与优化闭环 | 第 12–13 节验收/评估 | 借鉴指标与用例方法，不引入部署和展示任务 |

未来如需要 FastAPI、Redis/Celery、SSE 或 React，放在宿主服务/应用层：API 校验身份后调用 Runner；队列只投递 run_id 并触发 advance；LangGraph 仍是唯一流程调度器。队列的 queued/delivered 属于投递状态，不替换第 5.4 节执行状态，也不以 broker 的 result backend 作为运行事实源。

服务化时再补事务 outbox、重复投递处理和补偿扫描；消费方通过持久化 sequence 续读事件，连接断开不取消 Run。多租户登录/RBAC 由宿主实现，模板复用 ExecutionScope；不可将教程的工单/组织表硬编码到通用包。

在没有相应业务需求前，不增加 Redis、Celery、向量数据库、独立 RAG 服务、全套 UI、自动 Agent Marketplace 或自动长期记忆写入。扩展启用后必须接入既有的授权、版本冻结、台账、预算、事件与评估，不能成为绕过 Runtime 的第二条执行路径。
