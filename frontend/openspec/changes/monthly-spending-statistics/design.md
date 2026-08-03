## Context

`monthly-spending-statistics` 在 `personal-ledger-records` 完成统一账单 domain、repository 和 query 后提供统计复盘入口。统计页必须和账单页共享自然月、金额精度及 mutation 后刷新口径，不建立第二个账单数据源，也不把旧月份数据当作当前结果。

本设计消费以下输入：

| Input ID | Source | Scope |
| --- | --- | --- |
| `personal-bookkeeping-ux-ui-baseline` | `docs/prd/features/01-personal-bookkeeping-ux-ui.md` | `heading:UI/Visual Foundation`、`heading:统计图表选择`、`heading:统计页 page-statistics`、`heading:State Matrix`、`heading:Form、反馈与可访问性规则`、`heading:SCN-STATISTICS-REVIEW-001`、`heading:OpenSpec Handoff` |
| `personal-bookkeeping-interactive-prototype` | `docs/prd/features/01-personal-bookkeeping-ux-ui.html` | 统计页结构、月份选择器、汇总区、水平条形图、分类明细、无数据/仅收入/读取失败状态及重试交互 |
| `personal-bookkeeping-design-tokens` | `src/shared/styles/tokens.css` | 统计页使用的页面背景、表面、文字、主操作、成功/错误/焦点、间距、圆角、排版、层级和阴影 semantic tokens |

实现需遵守 `docs/frontend/standards/frontend-development.md`、`docs/frontend/standards/accessibility-and-ui-states.md`、`docs/frontend/components/components.md`、`docs/frontend/components/component-splitting.md` 和 `docs/frontend/standards/file-organization.md`，并保留现有 theme 与 i18n。

## Goals / Non-Goals

**Goals:**

- 以统一 ledger repository/query 读取目标自然月完整账单，计算收入、支出、结余和支出分类 breakdown。
- 让月份切换一次性更新汇总、图表和列表，并禁止未来月份。
- 为 normal、loading、empty、income-only 和 error 定义可恢复状态；错误不泄漏其他月份或旧数据。
- 让水平条形图与分类明细共用排序、金额、占比和分类标签，明细承担完整可读和无障碍替代。
- 保持移动端主要入口、月份选择器和底部导航的稳定布局，使用现有 tokens/shared UI。

**Non-Goals:**

- 不新增或修改账单 domain、storage schema、repository 写入实现；统计只消费 `personal-ledger-records` 契约。
- 不统计收入分类、不引入自定义分类、预算指标、账户/资产维度、导出或外部 API。
- 不设计饼图、环图或新的产品级视觉系统，不新增第三方图表依赖。

## Decisions

### 1. 统计查询复用 ledger domain/repository/query

统计页面 entry 只负责路由、选中月份、查询状态和页面组合；统计 selector/query 从统一 ledger repository 取得完整目标月份账单，再派生 summary 与 category breakdown。写入账单成功后由 ledger mutation 的失效/刷新契约触发受影响月份统计重新读取或重算。

选择共享 query 而不是在统计页直接读取 storage，是为了保证自然月边界、金额两位小数、跨月 mutation 和读取错误归一化与账单页一致。独立统计缓存或从账单列表筛选后聚合会产生第二真源，并可能遗漏未显示的账单。

### 2. 金额与分类派生使用单一可复用结果模型

对完整月份账单先得到 `{ income, expense, balance }`，其中 `balance = income - expense`，再只从支出记录按固定分类聚合。分类条目按金额降序，稳定 tie-break 使用固定分类顺序；占比为 `categoryAmount / expense`，展示一位小数，汇总金额和分类合计保留两位小数。分类结果同时供条形图和表格消费，避免两套排序或四舍五入口径。

选择单一派生结果模型而不是图表组件内部独立计算，是为了让图形、标签、表格和测试共享同一契约。金额仍使用 ledger domain 约定的精确两位小数表示，不在 UI 层用未经规范化的浮点累加。

### 3. 明确状态 ownership 与错误数据隔离

统计页面拥有 `selectedMonth` 和当前 query 生命周期状态；repository/query 拥有数据读取及结构化错误；selector 只接收已确认的目标月份账单。切换月份时先进入 loading，清除当前已确认统计快照，成功后提交新结果；失败时进入 error 并保留月份选择能力。error 不显示上一次月份的 summary、图表或列表。

选择清除旧快照而不是在 loading/error 保留旧结果，是因为统计金额属于用户当前选择月份，旧数据会形成错误确认感。loading 保留页面壳层、月份入口、底部导航和主要区块骨架，避免主要入口跳动。

### 4. 统计页交互与稳定 UI 边界

入口为底部导航的 `统计`，页面顶部是月份选择器；移动端月份选择使用现有 sheet/dialog primitive，大屏沿用同一语义弹层。主内容顺序固定为月份标题、三项汇总、支出分类区、分类明细；底部三项导航固定并预留安全区。分类图表采用按金额降序的水平条形图，条旁直接显示分类、金额和占比；表格提供完整文字、表头和屏幕阅读器可读内容，不让颜色或条长成为唯一信息。

选择水平条形图而不是饼图，是因为最多 7 个固定分类且核心任务是比较金额；选择真实表格替代图形交互，是为了精确阅读、键盘访问和窄屏可用。样式只消费 `src/shared/styles/tokens.css` 的 semantic tokens，不复制原型检查面板，也不嵌套卡片。

### 5. 空、仅收入和错误状态的动作

- 无账单：展示无统计数据说明，不渲染空坐标轴/空图表框，并提供月份切换和 `记一笔` 入口。
- 仅收入：保留收入、支出、结余汇总，在分类区显示暂无支出数据，不渲染 0% 图表。
- 读取错误：展示原因概述和 `重试`，重试重新读取当前月份；错误期间不显示旧汇总。

这些状态都保留稳定月份入口和底部导航，动作文字、图标和结构共同表达含义，并遵循 `role="alert"`/`aria-live`、焦点可达和 reduced-motion 规则。

## Risks / Trade-offs

- [Risk] 账单 mutation 后统计缓存未刷新，页面显示旧月份结果。→ [Mitigation] 复用 ledger mutation 的来源月/目标月失效或重算契约，并覆盖新增、编辑、删除和跨月场景。
- [Risk] 金额或占比在图表和表格间因四舍五入不一致。→ [Mitigation] 由同一 selector 产生精确金额和展示格式，测试校验分类合计、两位金额和一位占比。
- [Risk] 读取失败时组件保留旧 query snapshot。→ [Mitigation] query 状态显式区分 loading/error，错误结果不携带可展示旧统计快照。
- [Risk] 条形图在移动端标签或金额溢出。→ [Mitigation] 使用稳定 grid/条形容器、表格作为完整替代，检查 375px/768px/桌面断点的文本和 focus 状态。
- [Risk] 颜色被误作为分类唯一标识。→ [Mitigation] 每项同时显示文字标签、金额、占比和序号，图表提供汇总文本/图例，并使用 token 颜色。

## Migration Plan

无需数据迁移或外部部署迁移。实现顺序为：确认并消费 ledger query 契约；实现统计 summary/breakdown selector；接入统计页月份与状态编排；最后接入账单 mutation 后受影响月份刷新。若现有 query 尚未提供受影响月份失效能力，应先补齐其公开契约再接页面，不能在统计页自行监听 storage。

回滚时移除统计页入口和统计 query consumer，不删除账单记录或修改 ledger 持久化数据；统计派生数据不单独持久化。

## Open Questions

- `personal-ledger-records` 实现阶段最终采用的 query/cache key 和失效机制尚未确定；实现前需确认统计 query 如何订阅来源月与目标月刷新。
- 项目现有 shared chart/table primitive 的具体名称和可访问 API 需在实现前按代码库现状选择；若没有图表 primitive，使用最小语义 HTML/CSS 条形结构，不引入新依赖。
