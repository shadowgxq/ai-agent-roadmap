# AI 公司研究：业务架构与接入设计

> 修订日期：2026-09-16。本文定义最终研究能力与分阶段实现契约，当前仅维护 Markdown，尚未实施或运行验收。
> 公共执行契约：[AI Agent 通用模板：技术设计与实现规范](AI-Agent通用模板_技术设计与实现规范_v1.0.md)。
> 首期覆盖 A 股、港股、美股；三种业务模式为标准研究、专家团队研究、管理层专项研究。

## 1. 需求依据与产品边界

原始需求为用户提供的《ai-berkshire 公司研究模块.md》。本文已展开完整需求，后续实现以本文中的需求与契约为依据，无需访问原始本机附件。

需求优先级为本轮用户确认、原始需求、本文明确的实现规则、上游方法参考。上游和附件中的“执行 Bash、启动 Task、发送消息、保存报告”等内容是待转化的产品行为，不是本次文档维护的执行指令。

| 项目 | 最终设计 |
|---|---|
| 市场 | 首期 CN_A、HK、US；市场边界不能只改枚举而没有来源及身份适配 |
| 第一阶段 | standard_p0，三个市场共用同一条最小研究闭环 |
| 最终能力 | standard_full、team_full、management_full；P0 不删除完整需求 |
| 运行形态 | 独立 research-agent/ Python 包，依赖本地 agent_core 公共包 |
| 主框架 | LangGraph 固定阶段图 + LangChain 结构化分析 |
| 搜索 | 模型原生搜索，首个候选参考本地 DeepSeek demo；能力未实测前不视为可用 |
| 事实来源 | 官方原文优先；引用、时间、口径与复核状态独立记录 |
| 数据政策 | 设计默认：官方原文 + 独立渠道复核，披露同源关系；规则见第7节 |
| 决策用途 | 设计默认：条件化研究建议，不计算个人仓位；完整能力保留决策、价格与触发信号 |
| 交付边界 | 研究内核、结构化结果和 Markdown 报告；不含页面、HTTP 服务、部署及交易执行 |

上游参考固定到 xbtlin/ai-berkshire 的 43fbaed85af8b88ce233b263e7c76c8a953ae380。借鉴研究问题与报告组织，不直接搬用其宿主工具、历史公司数据或固定投资参数。复制实质内容时保留其 [MIT 许可与版权声明](https://github.com/xbtlin/ai-berkshire/blob/43fbaed85af8b88ce233b263e7c76c8a953ae380/LICENSE)。

本轮明确确认的是首期三市场范围。来源准出与决策用途采用本文标明的设计默认值，并非用户已确认或实际运行授权；它们是可替换的版本化policy，不应在编码时散落为隐式规则。

## 2. 原始需求到实现产物的映射

### 2.1 标准研究

| ID | 必须保留的需求 | 结构化产物/验收要点 | 阶段 |
|---|---|---|---|
| S01 | A/B/C 可研究性；AI 置信度与投资确定性分开 | ResearchabilityAssessment、覆盖理由、推算比例与冲突；不把资料少判为公司差 | B0 基础，B1 完整 |
| S02 | 近五年收入、净利润、利润率；近四季度变化 | FinancialSeries；每项有真实期间、披露时间和口径，缺失明确展示 | B1 |
| S03 | 分业务、FCF、现金/债务、研发、份额、管理层持股、当前估值、多空观点 | 财务与经营指标表、验证记录、空缺原因 | B0 核心指标，B1 完整 |
| S04 | 生意本质、客户付费、复购、硬件/软件/平台/服务、利润引擎、经营杠杆、粘性 | BusinessModelSection；一句话定义 + 分业务和价值流 | B1 |
| S05 | 品牌/定价、转换成本、网络效应、规模、技术/专利；过去5年及未来5–10年 | MoatAssessment；每类支持/反证、趋势、可复制性、破坏变量 | B1 |
| S06 | 失效/替代/竞争/监管/集中度/管理错误/衰退/估值透支；空方观点 | RiskRegister、BullBearSet；风险触发条件和影响路径 | B0 基础，B1 完整 |
| S07 | CEO/创始人决策、并购、回购、持股/减持、薪酬、稳定性、文化、离任影响 | ManagementBaseline；有重大疑问时建议专项，不自动扩大付费范围 | B1 |
| S08 | TAM/增速/天花板、产业链、议价、技术、集中度、长期结构趋势、10–20年重要性 | IndustrySection；事实、预测、情景与不确定性分开 | B1 |
| S09 | PE/PS/PB/EV、历史/同业、反向DCF、隐含增长、三情景、合理价格、安全边际 | ValuationRecord、CalculationRecord、AssumptionSet | B1 |
| S10 | 买入/观望/回避；空仓/持仓；建仓/加仓价；减仓/卖出信号；风险和置信度 | DecisionRecord 与价格/信号契约；数据不足明确 not_assessable | B1 |
| S11 | 全文来源和程序验算 | 断言/单元格引用、关键指标复核、计算与报告审计 | B0 起 |

### 2.2 专家团队研究

| ID | 必须保留的需求 | 实现与产物 | 阶段 |
|---|---|---|---|
| T01 | 四个独立 Agent 同期研究，各自搜索/获取信息/判断 | 四份角色上下文、查询记录、取证结果和报告；不是一个模型串行填四节 | B2 |
| T02 | 商业、财务、行业、风险管理层四角色 | 角色权限和 schema 明确，Lead 不代替首轮分析 | B2 |
| T03 | 进度、完成状态、核心发现、冲突可展示 | ResearchEvent 与 RoleProgress；本轮不设计前端 | B2 |
| T04 | 商业与财务、估值与行业、管理叙事与结果、数据冲突的交叉会审 | ConflictSet、定向复核、修订后的确定性计算 | B2 |
| T05 | 一句话结论、四维评分、核心数据、角色发现、多空、Checklist | TeamReport；每个评分有依据，不凭人数投票认定事实 | B2 |
| T06 | 激进/稳健/保守建议、具体价格、加减仓信号、数据抽检 | 三类条件建议、价格与信号引用、独立审阅和 AuditReceipt | B2 |

### 2.3 管理层专项

| ID | 必须保留的需求 | 产物/验收要点 | 阶段 |
|---|---|---|---|
| M01 | CEO/董事长/创始人/实控人/CFO/关键负责人/卸任影响者 | PersonMap，任期、经济权益、投票权和实际作用分开 | B3 |
| M02 | 近5年公开判断、正确/错误/反共识/过热时克制 | PredictionLedger；判断—结果—可评估性，不以后见之明重写原话 | B3 |
| M03 | 战略落地、目标实现、人才、纠错、危机、组织效率 | StrategyExecutionRecord | B3 |
| M04 | 承诺时间/内容/场合/结果/兑现率 | PromiseLedger，明确分母、部分兑现、覆盖率与样本数 | B3 |
| M05 | 业绩/股价/监管/竞争/事故/裁员等真实危机下的表现 | CrisisCase；沟通、担责、长期取舍及结果 | B3 |
| M06 | 并购/回购/分红/新业务/研发/现金管理逐项复盘 | CapitalAllocationLedger；投入、当时理由、结果、可归因局限 | B3 |
| M07 | 持股、AB股、VIE、薪酬、激励、减持、关联交易、董事独立性 | GovernanceAssessment，适用性与实际证据 | B3 |
| M08 | 员工/客户/商家供应商/同行/监管侧面验证 | StakeholderEvidence，具名事实与匿名线索分开 | B3 |
| M09 | CEO离任、组织依赖、继任者、团队深度、交接历史 | SuccessionAssessment | B3 |
| M10 | 35/25/25/15 加权；诚信否决；正直/能力/长期托付判断 | ManagementScore、IntegrityDecision、TrustConclusion | B3 |

## 3. 输入、模式与公共模板接入

### 3.1 ResearchRequest

| 字段 | 约束 |
|---|---|
| request_id | 幂等入口；同 ID 不同内容拒绝 |
| company_query | 原始公司名或证券代码；解析前不是已核实身份 |
| person_query | 专项可选，如“黄仁勋”；必须与公司及任期关联 |
| mode | standard / team / management |
| profile | standard_p0 / standard_full / team_full / management_full；与 mode 匹配 |
| market_hint / security_hint | CN_A / HK / US、交易所、代码、股类，可空 |
| as_of / timezone | 研究信息截止时点；缺省时在首次联网之前固定，展示默认 Asia/Shanghai |
| baseline_report_ref | 可选底稿；专项及团队可独立启动 |
| lookback_policy | 五个已披露财年；近期季度按真实可得披露 |
| budget_policy_ref / authorization_ref | 由调用方提供已批准额度与供应商/工具范围 |
| decision_policy_ref | 完整模式的估值/条件建议政策；P0 固定不提供定价决策 |
| parent_run_id / revision_scope | 补研究时新 run 使用；更新日期明确使用 refresh |

解析示例：“腾讯”必须识别上市主体与证券；“NVDA”不能只凭常识直接填 CIK；“王兴 美团”需要同时确认人物及企业；“某企业 A/H 两地上市”必须确定本次定价对象。

原始命令映射为 /investment-research→standard、/investment-team→team、/management-deep-dive→management；这些是调用方可用的业务别名，不在内核中实现聊天宿主的slash-command系统。报告默认简体中文，保留公司原名、原始币种和必要原文短引。

固定图也有 ResearchQuestion 计划表，但它是按 profile 展开的业务问题集合，不要求先完成通用动态 Planner。

### 3.2 接入接口

ResearchWorkflowPlugin 向 agent_core 注册 request/result schema、graph_factory、Skill、能力要求和 completion_policy。所有外部交换使用公共台账、预算和观测封装。

~~~~text
业务调用方
  → core.start + core.advance
    → ResearchState / 业务图
      → 原生搜索、原文读取、抽取、核验、计算、分析、审计
    → DeliveryManifest / ResearchResult
~~~~

业务只定义图、领域对象、计算和准出策略，不再实现第二套 retry、checkpoint、预算或 Langfuse 生命周期。

### 3.3 业务小状态

~~~~text
run_id / manifest_ref / request_ref / phase
identity_ref / researchability_ref / question_plan_ref
collection_ref / metric_snapshot_ref / calculation_set_ref
section_refs / role_result_refs / conflict_set_ref
coverage_ref / gap_round / report_revision
candidate_ref / audit_ref / delivery_ref
~~~~

大文档和原始响应在产物仓库。金额为十进制字符串；每个派生值引用输入 ID；所有产物沿用公共 ArtifactEnvelope。

## 4. 公司、证券、人物与三市场适配

### 4.1 身份契约

CompanyIdentity 保存 company_id、法定名/别名、注册地、行业、官方站点、entity_identifiers（如美股 CIK）、身份有效期与证据。一个公司可以关联多只证券。

SecurityIdentity 保存 security_id、company_id、market、exchange/MIC、ticker、share_class、instrument_type、quote_currency、上市状态/有效期、普通股/ADS 转换关系和出处。

PersonIdentity 保存 person_id、姓名/别名、company_id、职务、任期、控制/经济权益关系与证据；同名人物不能仅按名字合并。

第一阶段研究上市经营公司的普通股，以及转换关系有据的存托证券。ETF、衍生品、优先股等不纳入普通公司估值模板；不以代码长度猜市场。金融、地产、REIT 等可研究事实，但估值需行业专用政策，不套一般企业 FCF/DCF。

### 4.2 来源注册表

| 市场 | 第一手资料 | 第二渠道候选 | 身份/期间注意 |
|---|---|---|---|
| A 股 | [巨潮资讯](https://www.cninfo.com.cn/)、[上交所](https://www.sse.com.cn/)、[深交所](https://www.szse.cn/)、[北交所](https://www.bse.cn/)、公司 IR | 东方财富等可追溯的公开财务页面 | 合并/归母、累计季度、交易所与股类、公告更正 |
| 港股 | [披露易](https://www.hkexnews.hk/)、公司 IR | AASTOCKS 等公开财务页面 | 报告币种与报价币种、A/H、不同投票权、半年与季度可得性 |
| 美股 | [SEC EDGAR](https://www.sec.gov/search-filings)、公司 IR、对应交易所身份资料 | StockAnalysis 等公开财务页面；实际可用渠道由注册表登记 | CIK 与证券分离、不同股类、非自然财年、拆股、ADR/ADS |

候选站点不是已获授权、永久可用的 API。必须存具体公司页面/公告 URL、取数方法、更新时间及访问限制；不以首页作证据，不绕过访问控制。

三市场各需 MarketAdapter：resolve_identity、discover_filings、normalize_period、normalize_security_basis、source_profile。尚无适配时返回 market_source_not_configured，不能默默退到其他市场。B0 完成必须涵盖三个市场，不能先完成 A/H 后把美股放回远期。

SEC 的 submissions 和 XBRL 接口可作为美股取证实现入口，提供披露元数据与结构化财务资料；自定义标签、分部与特定上下文仍需回原文核对。[SEC API 说明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

### 4.3 美股与存托证券的补充规则

按发行人实际文件识别 10-K/10-Q、20-F/40-F/6-K 等披露，不假定所有美股公司都有同样季报。取得的结构化数字必须绑定 filing/accession、期间、单位和标签；不得把后来重述值倒灌到早期 as_of。

股价、每股指标、股本使用同一拆股口径。ADS 与普通股比例记录为“每份 ADS 对应 k 股普通股”，金额按同日汇率换算，不能把每 ADS 价格直接乘普通股总数。比例、拆股或发行生效日期不清时阻断相关估值。

## 5. 时间、研究范围与信息丰富度

### 5.1 时间语义

as_of 是本次可用公开信息的截止时间；retrieved_at 是实际读取时间，两者分开。缺省 as_of 在 Runner 登记冻结输入时确定；继续运行不刷新日期。

- publication_at 决定证据是否可在该时点使用；财报 period_end 不能替代公开时间。
- 官方更正、重述和管理层变动形成新版本，历史研究按当时可得版本。
- 历史网页只剩后来更新内容、无法证明当时版本时，标 temporal_unverified。
- 行情保存 quote_at、交易时区、交易时段、币种和延迟/来源状态；“最新”不等于实时。
- 财报、股本、现金/债务可能有不同观测日，必须检查是否存在重大后续变动并披露估值桥接日期。
- 已知同日发布但无具体时间，且影响日内截止判断时，不默认已在 as_of 前可得。
- 五年按真实财年，支持非12月年结及52/53周差异，不直接套自然年。
- 连续可比累计披露允许差分形成季度数并标 derived；不把半年数据除以二制造季度。

更新日期使用新 refresh run；同日修订保留 as_of，并让新增材料重新经过时间门禁。跨运行复用只复用仍可用的证据，不复用旧报告的“已核验”标签。

### 5.2 ResearchabilityAssessment

保存 grade、available_periods、source_types、可读原文比例、关键指标覆盖、推算比例、冲突数及理由。

| 等级 | 策略 |
|---|---|
| A | 信息充足；加强反共识、反证和市场已定价假设检查 |
| B | 基础资料可得；逐项标注推导与局限 |
| C | 信息不足；以客户、付费、替代、复制难度和管理行为开展第一性原理研究 |

评级描述公开信息条件，不是公司分数。analysis_confidence 与 investment_certainty 分别保存 high/medium/low + 理由，未校准时不输出假精确概率。

初评依据种子资料，完成取证后可以生成更新版本；最终报告引用最终覆盖对应的评级，不把初始猜测当作不可变公司属性。

### 5.3 ResearchQuestion 与覆盖

每个问题保存 question_id、topic、required、required_periods、expected_evidence、role、attempted_queries、evidence_refs、status、gap_reason。

status 使用 satisfied / not_applicable / not_disclosed / missing / conflict。not_applicable 必须有适用性理由；not_disclosed 必须有披露核查记录，不能用来掩盖未搜索。

完整度按适用需求判断。上市不足五年、没有合法季度披露时，明确展示实际期间和限制；若因此无法支持关键定价/决策，该部分仍不准出。非适用项可以有理由关闭，关键缺口不能靠缩小分母消失。

## 6. 原生搜索、读取与证据管线

### 6.1 查询与停止

每批查询对应一个问题或紧密相关问题组，包含已知身份、目标期间、所需来源、反证意图。身份确认前允许 company_ref 为空，用 raw_company_query 搜索，避免循环依赖。

默认工程上限为补检索最多2轮、报告修订最多2轮、单批协议续接最多4轮；均写入 profile 并可按明确配置调整。达到预算、时间、无新增证据或不可解歧义即停止，不用报告篇幅代替覆盖率。

四角色及各阶段共享 provider 级并发/速率限制；下载与单域名限制独立。费用与请求上限由调用方提供，不从教程样例推算真实消费。

### 6.2 适配器能力与协议

本地 demo/deepseek_websearch.py 包含 Anthropic 兼容请求及 server_tool_use/web_search_tool_result 识别，可作为首个候选适配器的源码参考。兼容性不等于每个账号、模型、工具版本都支持搜索、引用、限次和续接；官方兼容资料仅作协议入口。[DeepSeek 兼容接口](https://api-docs.deepseek.com/guides/anthropic_api/)

CapabilityProfile 按 provider、endpoint、model、tool_version、adapter_version 绑定，值为 supported / unsupported / unknown，至少涵盖：

~~~~text
native_search / observe_search_execution / read_source_urls
inspect_provider_citations / continuation / search_use_cap
domain_filter / date_filter / usage_breakdown / structured_output
~~~~

静态预检不付费；真实能力核验合并到首个已授权身份搜索，避免每个节点额外探测。每次返回仍检查本次是否真的搜索。

项目最小能力要求为实际搜索事件可观察、来源 URL 可读取、能够构建应用引用链。供应商 citation 不是唯一引用方案；有原文时可由应用建引用，记录 citation_mode=application。两者都不可用时阻断取证，不用模型自称“搜过”代替。

### 6.3 一次交换的边界

~~~~text
prepare_exchange → 公共台账调用 execute → 保存 raw response
  → normalize
      paused → 新 exchange_seq 原协议续接
      usable → 读取候选原文 → 抽取证据与指标
      empty → 记录缺口/有限改写
      tool_error → 分类恢复
      unknown → 对账/授权处理
~~~~

NativeStepResult 保存 transport_status、search_status、step_status、search_events、source_candidates、citations、continuation_ref、tool_errors、usage、raw_response_ref。未知次数/费用用 unknown/null。

传输成功、真实搜索发生、证据可用是三个独立判断。响应含工具错误也要保存；重试需新交换，不能反复使用错误缓存。normalize 无网络副作用。

需要续接时保留供应商 opaque 内容，不解密、不写普通日志、不跨供应商使用。若数据缺失或 adapter 不支持，明确能力不足，不能将半成品当成完整结果。供应商内部每次搜索之间不能假设存在本地 checkpoint。

### 6.4 DocumentSnapshot 与 Evidence

| 对象 | 必需字段 |
|---|---|
| DocumentSnapshot | snapshot_id、requested/final/canonical_url、publisher_id、origin_group_id、content_hash、publication_at、retrieved_at、mime、content_ref、parser_version、access_status |
| Evidence | evidence_id、snapshot_id、locator、quote、context_ref、question_ids、source_tier、temporal_status、extraction_method |
| SourceLineage | publisher、数据提供方、原始文件、处理渠道、independence_status、判断依据 |
| Claim | claim_id、kind、text、evidence_ids、calculation_ids、counter_evidence_ids、confidence、limitations |

PDF 保存文件页序与可得印刷页码、表格行列和单位；HTML 保存段落/表格定位。引用绑定具体内容 hash，不随网页更新自动换正文。

access_status 区分 fulltext / snippet_only / unreadable / low_quality_ocr。重要财务数字需要可定位原文；摘要只能作线索或带局限证据。OCR 数字未经人工或独立渠道核对不得直接作为定价输入。

Claim.kind 为 fact / derived / interpretation / gap。fact 需要证据；derived 需要计算；interpretation 必须引用依据和不确定性；gap 不得写成负面公司事实。

## 7. 数据核验与来源独立性

### 7.1 统一政策

设计默认source_policy=official_plus_independent_channel_v1：关键披露财务数据必须同时具备可定位的官方原文、独立渠道的取数复核、匹配的主体/期间/单位/口径、已解决的重大冲突和程序验算。

第三方独立整理同一份财报可以满足“第二渠道复核”，来源谱系仍标shared_origin、origin_group_count=1；报告只能声称官方披露与取数经过交叉检查，不能声称存在两次独立事实观察。自动生成的同一PDF镜像、同模型重读和来源关系不明的转载不满足第二渠道要求。

| 证据条件 | 指标准入与完整度影响 |
|---|---|
| 官方原文 + 可追溯独立渠道，口径一致，冲突解决 | 可满足本policy的关键财务核验；同源状态必须展示 |
| 官方原文 + 独立事实起源，口径一致 | 可用；同时记录独立事实支持 |
| 只有官方原文/镜像或同模型复读 | 可展示“单一官方披露”，关键项未满足则partial，相关定价不准出 |
| 只有第三方摘要，官方原文无法读取 | 降级线索，不作关键定价输入 |
| 来源谱系未知、关键数值冲突未解 | 补取证或blocked；不能把来源数量当核验通过 |

这个默认值将原始“双独立来源”要求具体化为财务披露的独立渠道核验，存在同源事实仍未被独立证实的局限。若采用更严格的independent_origins_v1，关键指标必须origin_group_count≥2且独立性有证据；仅同源复核时partial。切换须写入新policy版本并重做依赖核验，不能在同一run中静默放宽。

### 7.2 核验状态拆分

~~~~text
primary_status: verified / missing / unreadable
cross_check_status: independent_channel_checked / independent_origin_checked /
                    shared_origin_unchecked / conflict / missing
usability: usable / usable_with_limitations / blocked
~~~~

独立渠道复核与独立事实起源不是同一属性，分别保存 channel_count、origin_group_count 和依据。同一 PDF 的公司 IR、交易所镜像、缓存副本算同一原文；两个搜索引擎找到它也不增加事实来源数。

同一模型重新读一遍同一 PDF 属于抽取自检，不自动成为第二渠道。第三方复核需有可追溯页面/接口、取数记录和口径，不接受模型记忆值作对照。

重大监管事件、治理指控、竞争风险还需核查事实的原始出处与反方解释；财务抽取复核政策不能被泛化为“所有指控只需两个转载”。

### 7.3 比较规则

先匹配主体/证券、指标、期间、币种、单位、合并与调整口径，匹配后才能比较。

~~~~text
abs_diff = abs(a - b)
rel_diff = abs(a - b) / max(abs(a), abs(b))
~~~~

两者都为零时 relative=0，但仍检查零是否真实；一正一负默认冲突；接近零用指标绝对容差。比率用百分点差，不能把1%和1个百分点混用。

初始金额复核阈值：相对差≤1%只是“一致候选”；(1%,5%] 必须解释；>5% 阻断关键输入。允许的单位四舍五入误差由 metric_policy 另行定义。核验不是取平均数、中位数或多数票；阈值内仍需检查语义。

官方更正或明确的期间/单位解释可以解决冲突，但保存原观测、选值理由、排除记录与版本。不能让模型静默覆盖源数字。

## 8. 财务对象与确定性计算

### 8.1 MetricObservation 与 MetricSnapshot

MetricObservation 保存 observation_id、company_id、适用时 security_id、metric_code、原始文本、Decimal 值、unit_scale、currency、period_start/end、period_type、accounting_standard、consolidation_scope、adjustment_basis、share_basis、evidence_ids、publication_at 和 extraction_version。

MetricSnapshot 保存候选观测集合、选中观测、验证状态、选值理由、冲突与 snapshot_hash。上游原始值不可改写；修正通过新 observation/snapshot 表达。

period_type明确duration或instant：收入/利润是区间值，现金/债务/股数是时点值；instant允许period_start为空。TTM只拼接不重叠且口径一致的期间。稀释EPS、基本EPS、期末股数及加权平均股数分别保存，不能以一种分母代替全部每股指标。

禁止空值填0。合并净利润与归母净利润、GAAP/IFRS/调整后、持续经营与全部经营分别标识；不能用字段名相似推断可比。

### 8.2 计算函数契约

| formula_id | 定义/输入 | 不适用条件 |
|---|---|---|
| revenue_yoy | 本期收入/同期收入 - 1 | 基期≤0时标不适合常规增长率，另展示绝对变化 |
| net_margin | 同口径净利润/收入 | 收入≤0，或归属/期间不一致 |
| fcf_proxy | CFO - 正向表示的资本开支现金流 | CapEx定义不清；不得称为完整FCFF/FCFE |
| security_market_cap | 同一股类价格 × 对应已发行且在外股数（扣库存股；不是自由流通盘） | 价格/股份日不匹配、有未处理公司行动 |
| company_equity_value | 各经济权益股类市值经FX统一后求和 | 不能重复计入ADR对应原股；无法确认股类价值时不可算 |
| pe | 股价/同股类、同币种、同拆股口径EPS，标TTM或FY | EPS≤0，或期间/股类不匹配 |
| ps / pb | 匹配整体权益市值/收入或普通股权益；或一致的每股口径 | 错误范围；收入/权益≤0时不作常规定价比较 |
| roe | 同期归母净利润/平均归母权益 | 平均权益≤0；不拿 EPS/BVPS 当精确ROE |
| roa | 同期明确利润口径/平均总资产 | 口径不明、分母异常 |
| ev | 全部普通权益价值 + 债务 + 优先权益 + 少数权益 - 可扣现金 | 各项定义和日期无法桥接；不得漏加或重复 |
| fcf_yield | 明确的股权现金流/整体权益市值，或FCFF/EV并单独命名 | FCF代理与FCFF/FCFE混用；负值不能推出“便宜” |
| commitment_rate | 第12节定义的到期承诺兑现数/可评估总数 | 无合格分母返回 null |

CalculationRecord 保存 formula_id/version、input_metric_ids、input_snapshot_hash、parameters、result、unit、applicability、warnings、display_precision。单位归一和金额运算用 Decimal；数值求根可用指定数值方法，保存容差与收敛结果。

汇率单独是有来源、quote_at、base/quote_currency 的输入；财报原币保留，展示换算不改变原始事实。企业总权益、某一股类市值、EV 三者不得互换。

## 9. 标准工作流与 P0 可实现闭环

### 9.1 完整阶段

~~~~text
冻结输入/预算/政策 → 静态预检 → 身份取证/歧义澄清
  → 可研究性 → 问题矩阵
  → 财务经营取证 → 归一复核 → 程序计算
  → 商业模式 → 护城河 → 行业长期趋势
  → 基础管理层 → 逆向风险/Bull vs Bear
  → 估值与情景 → 决策
  → 候选报告 → 审计 → 交付
~~~~

阶段产出结构化 Claim/Section；缺口进入受限补取证，再使相关下游失效重算。标准模式是一个主分析上下文；下载可并发，但不因此宣称专家团队研究。

### 9.2 standard_p0 必需范围

每次研究一家公司，三个市场都支持：

1. 无歧义的公司和证券，及实际最新已公开年报。
2. 最新完整财年与上一可比财年的收入、明确归属的净利润、CFO、定义清楚的CapEx、现金和债务。
3. 官方原文、来源核验状态、时间/单位/币种/合并口径。
4. 一句话商业模式、收入来源、主要风险和反证查询记录。
5. 可适用的收入同比、净利率、FCF代理；行情、市值和PE只作可选扩展。
6. 有缺口标记的简版报告、逐项引用、计算记录、审计与恢复能力。

某个必需指标未披露或不适用时必须说明；对普通适用公司必需数据取不到，P0 为 partial。特殊行业的通用FCF不适用可关闭该项，但不能给出未支持的行业估值。

~~~~text
mode=standard
profile=standard_p0
result_quality=complete|partial|blocked
full_mode_coverage=partial
decision=not_assessable
~~~~

P0 报告标题明确“简版”，列出完整模式未覆盖项；P0 complete 只表示上述子集完成。

### 9.3 P0 节点合同

| 节点 | 读取 → 产出 | 路由与失败边界 |
|---|---|---|
| preflight | 冻结配置 → 能力/预算检查 | 未配置返回阻断说明，不先付费探测 |
| collect_identity | 原始查询 → 身份候选证据 | 无结果记gap；多主体进入clarify |
| resolve_identity / clarify | 候选 → 身份或固定问题 | 经公共interrupt/resume，等待节点不联网 |
| assess_researchability | 种子来源 → A/B/C与理由 | 信息少改变策略，不伪造覆盖 |
| build_questions | profile/身份 → 问题与取证批次 | 固定范围，模型只有限改写查询 |
| collect_evidence | 批次 → 原文/Evidence/observations | 复用公共台账；未知费用不盲重发 |
| normalize_verify | 观测/策略 → MetricSnapshot | 口径冲突不平均 |
| assess_coverage | 问题状态/预算 → 足够/补充/降级/阻断 | 有增量机会才补，最多2轮 |
| calculate | 可用指标 → 计算与不适用项 | 不接收自由Python或eval |
| analyze | 证据/计算/局限 → sections/claims | 不创造新裸数字 |
| compose_candidate | 冻结sections → Markdown+引用映射 | 新report_revision，不覆盖旧正文 |
| audit_candidate | report_hash/依赖 → AuditReceipt | 数字错误、引用不实必须修订 |
| revise_candidate | failed_check_ids → 定向修订范围 | 文本→重组稿；数字→重核验/计算；缺证据→补取证 |
| finalize | 有效候选/审计 → DeliveryManifest | 错误未修正不能发布partial报告 |

未知代码异常和持久化故障由 Runtime 停图，不能一律路由到“数据不足”。

取证子图按一轮交换/一份文档形成可恢复边界。主图只存 collection_ref，内部保存 batch_cursor、exchange_ref、document_cursor、已保存结果引用与循环次数。

## 10. 估值、价格与决策输出

### 10.1 决策用途

设计默认decision_policy=conditional_research_v1：基于公开数据，输出明确的买入/观望/回避判断、合理价格区间、建仓/加仓条件、减仓/退出信号，区分空仓者和持仓者；团队报告再区分激进/稳健/保守三类条件。

这些是研究情景，不读取或推断个人资产、持仓成本、收入、负债及可承受损失，不输出个人买入股数、资金比例或自动下单指令。风险层次是报告比较维度，不是对用户适当性的评定。

报告说明结论基于何时的数据、哪些假设、价格触发条件和失效因素。P0不输出具体操作判断；完整模式不以“仅供参考”为理由省略需求中的决策与价格章节。若以后增加个性化仓位，需独立扩展用户输入、风险约束及输出契约，不悄悄加入当前模式。

### 10.2 估值范围

standard_full 与 team_full 必须覆盖适用的当前估值、历史比较、同行比较、反向DCF及悲观/中性/乐观情景；不适用项须给理由和替代方法，未取得必要数据不能当作不适用。

AssumptionSet 保存增长、利润率、再投资、终值、折现率、币种、期限、证据、理由、范围和policy_version。模型提出假设，程序检查有效性并执行计算；假设不是已验证事实。

历史估值使用当时可得财务与同口径价格，不能用后来的财报回填。同行名单有选择理由、行业/业务/会计可比性和排除项，避免只挑便宜或支持预设结论的公司。

### 10.3 DCF 与反向 DCF

~~~~text
FCFF路线：
EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^N
TV = FCFF_(N+1)/(WACC-g)，要求 WACC>g
股权价值 = EV + 可加非经营资产 - 净债务 - 优先权益 - 少数权益
~~~~

桥接项依据所选现金流定义逐项检查，现金/债务不能重复调整。FCFE使用股权资本成本，直接得到股权价值，不重复扣净债务。每股价值匹配对应经济权利、稀释假设及股类。

净债务中的可扣现金不能再计入“可加非经营资产”；债务/租赁、优先权益、少数权益和合并现金流范围必须一致。FCFF可由EBIT税后经营利润、折旧摊销、CapEx和营运资本变化构建；CFO-CapEx代理不能未经调整直接充当FCFF。无公开交易价的股类需有可审计的经济权利映射/估计政策，否则整体权益估值不能冒充直接观察到的市值。

反向DCF指定只求解的参数、其他固定假设、搜索区间、精度和收敛上限，返回 solved / no_solution / multiple_solutions / invalid_inputs，不凭模型直接报隐含增速。

三情景逐项给假设、价值区间和敏感性。未经说明不概率加权，不把四角色票数当概率。上游固定r/g/终值倍数属于可选方法政策，不硬编码为普遍规则或实时市场数据。

### 10.4 DecisionRecord

~~~~text
decision: buy | watch | avoid | not_assessable
thesis_summary / confidence / investment_certainty
valuation_ref / quote_ref / as_of
fair_value_range / entry_range / add_range
actions_for_unheld / actions_for_held
risk_profiles[aggressive, balanced, conservative]
increase_signals / reduce_signals / exit_signals
key_risks / invalidation_conditions / limitations
~~~~

价格结构固定为 low、high、currency、security_id、basis_date、valuation_ref、policy_ref；low≤high，普通股价格区间为正。所有价格均来自计算结果；无依据时为 null 并给 reason。

定价政策保存所选情景、明确的安全边际参数和理由。条件价格可用“参考每股价值 × (1 - 安全边际)”计算；三个风险层次以安全边际、可接受假设和证据门槛区分，不只是修改文案，也不随意预设固定折扣。

### 10.5 决策门禁与信号

- buy：生意/治理/财务基本条件通过，价格落入政策认可区间，关键反证已处理，定价输入有效。
- watch：公司可以评估，但价格、催化或可观察条件尚未满足；写明等待条件。
- avoid：有充分证据支持重大经营/治理/估值风险，给出原因和可能改变判断的条件。
- not_assessable：关键证据或适用估值缺失；不能用 watch 掩盖“不知道”。

估值可计算时仍输出合理区间；avoid 不意味着隐去所有价格。若核心诚信/经营门禁失败，建仓/加仓区间可以为 null 并注明“风险条件未解除”，不机械给诱导性价格。

Signal 保存类型、观察指标/事件、比较条件、阈值及单位、适用期限、source/calculation_refs、触发后的建议。它是供未来复查的条件，不表示后台已在监控。持仓者卖出条件同时考虑基本假设失效和价格因素。

完整研究中不能省略决策章节；有证据就给明确条件结论，证据不足就保留章节并列出不可评估原因。

## 11. 专家团队：四个真实独立研究分支

### 11.1 角色合同

| 角色 | 任务 | 工具与输出 |
|---|---|---|
| Business Analyst | 生意、收入/利润引擎、用户价值、定价、护城河、协同与可持续性 | 搜索/读取/抽取；BusinessRoleReport |
| Financial Analyst | 3–5年财务、利润率/ROE/ROA、现金流/CapEx、债务、历史/同行/情景估值 | 搜索/读取/计算/复核；FinancialRoleReport |
| Industry Researcher | 规模/增速/渗透、份额、对手、细分格局、产业链、技术/政策/替代 | 搜索/读取/抽取；IndustryRoleReport |
| Risk & Management Assessor | 诚信/资本配置/治理、监管/竞争/新业务/周期、长期颠覆风险 | 搜索/读取/抽取；RiskRoleReport |
| Team Lead | 任务分配、预算、差异会审、综合 | 读取已登记结果；定向调查仍派给有权限的角色 |
| Reviewer阶段 | 数值/引用/口径与核心断言审阅 | 独立上下文读取证据；可复用模型，不常驻第五个研究员 |

四个角色同批启动，网络调用受provider并发限制；需观察到独立角色的活动时间有实际重叠，串行四次调用不能验收为“并行团队”。共享同一模型不意味着四个统计独立专家。

### 11.2 图与独立性

~~~~text
身份/可研究性 → team_dispatch
  ├─ business_subgraph ──┐
  ├─ financial_subgraph ┤
  ├─ industry_subgraph ─┤→ 显式join
  └─ risk_subgraph ─────┘
→ 事实对齐 → 冲突分类 → 定向复核（最多2轮）
→ 必要的估值重算 → Lead综合 → 独立审计 → 交付
~~~~

共享身份、as_of、版本、预算政策及不可变原文缓存；首轮不共享其他角色结论、messages 和查询历史。每个角色至少有自己的真实搜索记录、证据选择及独立分析；共享PDF不增加独立来源数。

固定父分支写各自 result_ref，join等待四个终态结果。可降级的领域失败转换成failed角色产物；持久化/未知程序异常继续抛出，由公共恢复处理，不能为凑齐join吞掉异常。

### 11.3 冲突、评分和进度

事实冲突先核主体、时间、币种、单位、合并/调整口径；解释冲突保留双方证据与反驳；假设冲突重算情景；未解冲突保留，禁止投票或平均成事实。

四维均采用1–5分，数值越高表示该维度越有利；风险维度明确叫“风险韧性”，避免风险越大分越高。1/2/3/4/5对应重大不利/明显不足/利弊并存/优势较强/优势充分且反证较弱，评分需指标依据、反证和理由。

本项目默认四维等权综合，完整四维可评估时才计算平均；缺项返回 null。此为展示政策，不是投资概率，也不是管理层35/25/25/15权重。重大风险门禁优先于综合分。

RoleProgress 包含 pending/running/completed/failed/interrupted/cancelled、当前阶段、已验证核心发现、task_attempt_id、时间与冲突状态。事件只展示已登记事实，不发送模型内部思考，不用固定计时伪造百分比。

### 11.4 报告与降级

团队报告包括一句话决策、四维及综合分、核心数据、每角色主要发现、共识/分歧、Bull vs Bear、买入Checklist、三类风险条件建议、具体价格、加减仓信号和抽检结果。

Checklist 固定覆盖：生意可理解、需求持续、护城河、盈利与现金、资产负债、资本配置、诚信与利益一致、行业与替代、价格与安全边际、关键反证。每项 pass/fail/unknown + evidence_refs，不以“通过项多”抵消诚信或关键财务失败。

一个角色未完成只能partial/blocked，明确缺哪个；财务角色失败禁输出定价。Lead失败保留角色产物，新revision可只重做综合。已结束草稿补跑通过新run，不用普通continue重跑成功角色。

## 12. 管理层专项：人物、事件和评分

### 12.1 独立入口与采集

既支持“公司”也支持“人名 + 公司”。无底稿时可独立开始；引用标准报告时重新确认主体、任期、as_of和证据版本。

四组取证任务为：公开判断与承诺、资本配置、治理薪酬、利益相关方反馈。它们可并行采集，最终按人物/事件归一；不是必须再造四个自由对话 Agent。

~~~~text
人物识别 → 四类取证 → 事件/承诺账本
→ 战略与执行 → 危机表现 → 资本配置 → 诚信/治理
→ 接班与关键人物依赖 → 加权评分/诚信门禁 → 审计/报告
~~~~

### 12.2 最小账本

| 对象 | 必需信息 |
|---|---|
| Prediction | person_id、stated_at、原话/场合、可检验判断、期限、结果证据、correct/incorrect/mixed/not_due/unobservable |
| Promise | promise_id、去重主题、person_id、stated_at、deadline、目标/单位、source_evidence、outcome_metric/evidence、status、assessment_as_of |
| CrisisCase | 危机时间/类型、当时约束、沟通与决策、利益相关方影响、后续结果与反证 |
| CapitalAllocationEvent | 类型、宣布/完成时间、金额/币种、当时理由、融资方式、机会成本、结果指标/期间、局限 |
| GovernanceFact | 股权/表决权/激励/关联交易/董事职责、有效日期、证据及适用性 |
| StakeholderSignal | 角色、具名/匿名、日期、原话、利益关系、代表性限制、核实状态 |

同一承诺在多次电话会重复出现只算一个；修订保存原版本、修订时点和原因，不能把未兑现承诺从分母删除。模糊愿景不是可量化承诺；结果尚未到观察期不能判失败。

### 12.3 兑现率、覆盖率与阈值

Promise.status 为 fulfilled / partially_fulfilled / not_fulfilled / not_due / unobservable / ambiguous。

~~~~text
E = fulfilled + partially_fulfilled + not_fulfilled
完全兑现率 = fulfilled / E
可评估覆盖率 = E / 全部已到期承诺数
~~~~

部分兑现留在分母并单独报告，不默认折半；未到期不算失败，已到期但无法观察/语义不明降低覆盖率。无分母返回 null。

初始policy要求 E≥5、可评估覆盖率≥60% 才展示等级；这是可调整的工程启发式，不是经过统计校准的诚信标准。未达门槛仍展示原始记录、比率及“样本不足”，不按小样本判人。

等级边界为 >80% 优秀、[60%,80%] 基本合格、[40%,60%) 待关注、<40% 明显不足；等级仅描述这批可评估承诺，不直接等价人格结论。战略预测准确度单独统计，不混入承诺兑现率。

### 12.4 加权评分与诚信否决

每维1–5分，附证据、反证与理由：

~~~~text
综合分 = 诚信 × 35% + 战略与执行 × 25%
       + 资本配置 × 25% + 治理 × 15%
~~~~

缺少任一维度不补3分、不重分配权重，综合分为null并披露已覆盖权重。没有负面线索不等于诚信满分；资本配置需可归因结果，不能只凭股价上涨打高分。

IntegrityDecision 为 clear / concern / veto / insufficient_evidence。veto需主体匹配、原始可追溯重大事实、事实与指控分开、有效时间和独立审阅。匿名帖子或单一未经核实指控不能触发veto。重大争议证据仍不清则needs_review并阻断肯定托付结论。

最终回答“是否正直”“是否有能力”“是否愿长期托付”，使用 yes / conditional / no / not_assessable，保留理由。veto阻断正向托付，不通过高综合分抵消。

### 12.5 最终报告

人物地图、近5年判断—结果、战略执行、承诺账本/兑现率/覆盖率、困难时期表现、资本配置、治理、各利益相关方核实、接班风险、四项分数/综合分/否决与长期托付结论。公开信息不足的具体部分必须可见。

## 13. 报告、审计与结果合同

### 13.1 报告最低结构

standard_full按以下顺序输出：结论与as_of；信息丰富度及两种置信度；公司/证券与业务速览；五年财务/近期经营/分部数据；一句话商业模式；五类护城河与趋势；行业竞争与长期变量；基础管理层；风险与Bull vs Bear；当前/历史/同行/反向DCF/三情景估值；决策与空仓/持仓条件建议；价格及加减仓/退出信号；缺口、来源、计算和配套审计引用。

standard_p0保留范围声明、身份、可研究性、两年核心数据、商业模式、基础风险、可复算指标、未覆盖项和来源附录。团队和专项按第11、12节的完整结构渲染，不能只交一份Lead摘要或一张评分表。

结构化结果是正式输入，Markdown只作确定性展示；渲染阶段不得再次让模型改数字。每个表格数值绑定metric/calculation ID，每条关键断言绑定Claim ID，引用标识解析到具体原文位置。首次候选报告包含局限声明，审计回执通过独立交付清单关联。

### 13.2 三个不可变产物

~~~~text
CandidateReport(report_revision, content_hash, citation_map, input_refs)
  → AuditReceipt(target_report_hash, policy_hash, checks, verdict)
  → DeliveryManifest(report_hash, audit_hash, result_quality, gaps)
~~~~

报告正文不回写“本报告审计通过”，审计结果在配套manifest/receipt中展示。改动任何正文、数字或引用都产生新版本、新hash和新审计。

delivery_id 由 run_id、report_hash、audit_hash、release_policy_version 决定；重复finalize返回原manifest。blocked可只有失败/缺口清单，report_ref为空，不能伪造一份通过审计的正式报告。

### 13.3 审计规则

| check | 内容 | 执行方式 |
|---|---|---|
| identity/time | 企业/证券/人物和期间一致，as_of可用 | 确定性校验+来源日期 |
| source_policy | 关键指标满足当前来源政策，谱系披露真实 | 规则与验证记录 |
| references | 所有引用ID、正文、定位和版本存在 | 全量检查 |
| numbers | 报告数值等于指标/计算显示值 | 全量检查关键数字；P0全量数字 |
| accounting | 单位/币种/归属/股类/会计口径有效 | 确定性规则 |
| semantic_support | 原文真正支持断言，未把预测当事实 | 独立模型上下文辅助审阅 |
| counter_evidence | 关键主张处理反证或明确未找到/未解决 | 规则+审阅 |
| scope/decision | P0未冒充完整版；价格/评分/决策准出有效 | profile规则 |
| lineage | 计算与章节依赖当前被选版本，无混用旧值 | 依赖hash检查 |

完整报告中非关键数字可以用固定seed抽检15%，样本数ceil(N×15%)，N=0标不适用；保存全集、样本和结果。关键价格、财务、管理层重大判断不走抽样替代。任一抽样失败扩大到相关类别全检并修订，不换seed直到抽过。

语义审阅与初稿分开上下文，接收正文、原始证据和反证；不能用生成器自报置信度作为审计。计算由代码审，模型不给自己心算结果盖章。

### 13.4 状态与准出矩阵

| 状况 | result_quality | report/decision规则 |
|---|---|---|
| 本profile适用必需项完成且审计通过 | complete | 完整模式按证据给明确决策；P0仍not_assessable |
| 有可审计内容，但存在未覆盖维度/角色/关键输入缺口 | partial | 披露缺口，禁止没有依据的定价与肯定结论 |
| 身份无法确认、不能取证、没有足够可信内容 | blocked | 交付阻断说明，report_ref可为空 |
| 已知数字错误、虚假引用、关键语义不支持 | 不准发该候选 | 修订后重新审计；不能只改标签为partial |
| 程序/数据库异常导致流程未结束 | 质量为空或保留历史产物 | execution_status为失败，不伪装交付完成 |

partial只容许“不完整但已呈现内容可靠”。缺完整研究必需估值时，standard_full不得complete；管理层报告无可量化承诺属于样本限制，不能编造分数满足模板。

### 13.5 ResearchResult

~~~~text
run_id / mode / profile / company_ref / security_ref / as_of
execution_status / result_quality / full_mode_coverage
researchability_ref / analysis_confidence / investment_certainty
decision_ref / valuation_ref / management_conclusion_ref
report_ref / role_report_refs / audit_ref / delivery_ref
gaps / conflicts / recommended_followups
usage_summary / observability_status / reproducibility_manifest_ref
~~~~

非适用结果字段为null；AI置信度、商业确定性和评分三者不互换。usage_summary包含已知费用、未知预留及估算状态；Langfuse trace并非事实审计依据。

## 14. 修订、依赖失效与恢复

公共模板负责通用恢复，业务负责判断哪些内容还能用。

| 变更 | 必须失效重做 |
|---|---|
| 仅措辞调整 | Candidate、Audit、Delivery |
| 替换引用位置或原文版本 | 依赖的Claim与报告审计；内容改变则重新评估指标 |
| 更正财务数字/币种/期间 | 相关MetricSnapshot、计算、分析、估值、报告与审计 |
| 股类、ADS比例或拆股变化 | 价格/股本/每股指标和所有相关估值；企业财务另核归属 |
| 行业假设变化 | 情景、反向DCF依赖、价格/信号、综合结论 |
| as_of改变 | 新refresh run，重审全部时间有效性 |
| 来源/评分/估值政策变化 | 依赖该政策的核验、评分、计算和审计 |
| 团队某角色补跑 | 该角色及依赖它的冲突会审、综合、计算和报告 |

第一版用显式 input_refs/hashes 即可，不需要图数据库。复用旧证据有ReuseRecord，说明出处、有效性重查和本次接受理由。

如果是原图故障且尚未结束，continue；如果等待人工问题，resume；供应商paused走内部协议续接；已经结束partial补证据，新revise run。新日期研究创建refresh，不能混在旧run继续。

## 15. Skill、政策与代码落点

### 15.1 业务目录

~~~~text
research-agent/
  pyproject.toml
  src/research_agent/
    contracts.py
    state.py
    plugin.py
    graph.py
    collection.py
    native_search.py
    documents.py
    identity.py
    metrics.py
    calculations.py
    analysis.py
    reporting.py
    policies.py
    markets/
      cn_a.py
      hk.py
      us.py
    workflows/
      team.py          B2
      management.py    B3
  skills/
    investment-research/
    investment-team/
    management-deep-dive/
    shared/
~~~~

核心文件按实现进展创建，不要求先铺空目录。三市场适配共享证据与计算协议；不是维护三套独立Runtime。

业务追加的角色证据写在各自命名空间，统一交付由finalize负责；不引入Coder角色专门替研究员保存文件。

### 15.2 Skill 和共享策略

三个Skill分别定义方法、阶段、问题、输出语义与模式准出。shared保存source、metric、valuation、scoring、report政策及版本。manifest声明workflow_id、profile、input/output_schema、能力、工具、政策和上游出处。

冻结完整Skill与policy资源后写入RunManifest；恢复不读取最新可变文件。上游方法名可作为视角标签，不伪造大师本人语录或真实评价。

## 16. 实施顺序、责任和验收

### 16.1 实施任务

| 任务 | 责任模块 | 依赖 | 实现结果 |
|---|---|---|---|
| B0.1 请求与三市场身份 | contracts/identity/markets | 模板T0 | 公司/证券/人物输入、冻结as_of、市场适配与歧义处理 |
| B0.2 原生取证闭环 | collection/native_search/documents | 模板T1–T2、B0.1 | 实际搜索可观察、原文/来源/续接/错误对象 |
| B0.3 核验计算 | metrics/calculations/policies | B0.2 | 核心财务、来源复核、Decimal计算及不适用项 |
| B0.4 简版报告 | analysis/reporting/graph | B0.3 | P0报告、审计、交付、缺口及公共恢复 |
| B1 完整标准研究 | 标准Skill/analysis/valuation/reporting | B0 | S01–S11全部适用需求，完整决策与价格合同 |
| B2 专家团队 | workflows/team + 模板T4 | B1 | T01–T06、四角色并行、会审、评分与三类建议 |
| B3 管理层专项 | workflows/management + 管理层Skill | B0、共享报告/审计 | M01–M10；运行时不强制先有标准或团队报告 |
| B4 供应商/行业扩展 | adapters/行业policy | 真实覆盖缺口 | 增加确有需要的provider/行业，不借机扩大基础平台 |

建议顺序B0→B1→B2→B3；B3的技术依赖不包括B2，排期可以独立调整。三市场范围从B0开始生效，美股不是B4扩展项。

### 16.2 后续验收案例

本轮只定义验收，不运行测试、服务、数据库或真实模型。

| 范围 | 后续需要证明 |
|---|---|
| 三市场 | A股/港股/美股各至少一例走完同一P0链；身份与原始披露适配真实有效 |
| 特殊身份 | 同名、多地上市、不同股类、ADR/ADS歧义不会猜测合并 |
| 时间 | 历史as_of排除后来财报/重述；恢复不混新行情；非自然财年正确 |
| 期间 | 无季报明确not_disclosed；累计差分可追溯；不填造季度 |
| 来源 | 同PDF镜像不增来源；官方/第二渠道关系与准出政策一致 |
| 数值 | 负/零分母、币种错配、股类错配、单位数量级和FCF口径能阻止错误估值 |
| 搜索 | 未发生真实搜索、HTTP200工具错误、paused/empty/unknown均有不同处理 |
| 恢复 | 响应保存后不重复付费；未知响应保留预留；过期回答拒绝 |
| 报告 | 改数字使审计失效；已知错误不能通过partial发布；P0不冒充完整研究 |
| 标准 | 完整财务、商业/护城河/行业/管理/风险/估值和S10全部输出可追溯 |
| 团队 | 四角色独立搜索与实际并发；四维、冲突、Checklist、三类建议及失败降级 |
| 专项 | 部分兑现留分母、未到期不算失败、样本不足不打满分、匿名线索不触发veto |
| 观测 | 真实进度事件、断线续读、Langfuse故障隔离与本地事实完整 |

后续比较单Agent与团队时，在相同公司、as_of、证据口径和预算条件下比较完整度、错误率、冲突处理、费用与耗时；不能预设四Agent天然更好。

## 17. 运行配置与参考

后续真实运行前由调用方配置：具体provider/endpoint/model/tool_version及凭证引用、有限请求/token/时长/费用预算、hard或soft模式、unknown重发政策、数据库/产物位置、Langfuse或Noop。没有配置就静态阻断，不以“待确认”为由随意填真实付费额度。

估值参数、同行选择和评分启发式属于版本化研究政策与每次可审计假设；文档不预先填写真实公司的股价、收益率、资本成本或投资结论。

参考方法源固定到上述提交；它们补充方法背景，需求覆盖以用户原始附件及本文映射为准：

- [标准研究方法](https://github.com/xbtlin/ai-berkshire/blob/43fbaed85af8b88ce233b263e7c76c8a953ae380/skills/investment-research.md)
- [团队研究方法](https://github.com/xbtlin/ai-berkshire/blob/43fbaed85af8b88ce233b263e7c76c8a953ae380/skills/investment-team.md)
- [管理层研究方法](https://github.com/xbtlin/ai-berkshire/blob/43fbaed85af8b88ce233b263e7c76c8a953ae380/skills/management-deep-dive.md)

这些来源的宿主命令、联网结果与历史报告都不构成本项目已经实现或验收通过的证明。
