## 1. 统一账单数据与统计派生

- [ ] 1.1 [logic] 确认并接入 `personal-ledger-records` 的 ledger domain/repository/query 契约，按交易日期本地 `YYYY-MM` 获取完整目标月份账单，不在统计模块直接读取 storage；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:OpenSpec Handoff`、`heading:统计页 page-statistics`）、`personal-bookkeeping-interactive-prototype`（统计页数据结构）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css` 不适用逻辑边界）。
- [ ] 1.2 [logic] 实现月度 summary selector，使用统一 ledger 金额口径计算收入、支出和允许为负的结余，显示金额统一两位小数；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计页 page-statistics`、`heading:SCN-STATISTICS-REVIEW-001`、`heading:OpenSpec Handoff`）。
- [ ] 1.3 [logic] 实现仅针对支出的固定分类聚合，按金额降序稳定排序，计算分类合计和一位小数占比，并让图表与明细消费同一结果模型；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计图表选择`、`heading:统计页 page-statistics`、`heading:SCN-STATISTICS-REVIEW-001`）。
- [ ] 1.4 [logic] 复用 ledger mutation 的来源月/目标月失效或重算机制，覆盖新增、编辑、删除和跨月迁移，保证成功后统计最新、失败无部分更新；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:State Matrix`、`heading:OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（账单 mutation 后统计更新结构）。

## 2. 统计查询状态与页面数据流

- [ ] 2.1 [logic] 建立统计页面 query 状态模型，区分 loading、normal、empty、income-only 和 error；切换月份时清除旧统计快照，读取失败时不返回其他月份或旧数据，并提供当前月份重试；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:State Matrix`、`heading:统计页 page-statistics`、`heading:Form、反馈与可访问性规则`）。
- [ ] 2.2 [logic] 实现当前月默认、已有账单历史月份选择和未来月份禁用/拒绝规则，使月份切换同步驱动 summary、breakdown 和明细列表；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计页 page-statistics`、`heading:SCN-STATISTICS-REVIEW-001`）、`personal-bookkeeping-interactive-prototype`（月份选择器交互）。
- [ ] 2.3 [logic] 将统计 selector 输出映射为页面所需的汇总、条形图条目和分类表格数据，确保标签、金额、占比、排序和颜色元数据一致；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计图表选择`、`heading:SCN-STATISTICS-REVIEW-001`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）。

## 3. 统计页 `page-statistics`

- [ ] 3.1 [ui] 实现统计页 entry 的页面级 composition、月份选择器、三项月度汇总和统一底部导航入口，保持当前月默认及未来月份禁用的可见反馈；Use $frontend-design；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计页 page-statistics`、`heading:UI/Visual Foundation`、`heading:OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（统计页结构）。
- [ ] 3.2 [ui] 实现按金额降序的水平条形图，条旁展示分类名称、两位小数金额和一位小数占比，并提供图例/汇总文本及键盘、触摸可达的分类项；Use $frontend-design；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计图表选择`、`heading:统计页 page-statistics`、`heading:Form、反馈与可访问性规则`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）。
- [ ] 3.3 [ui] 实现分类明细表作为图表的精确阅读和无障碍替代，展示序号、分类、金额和占比，确保内容不依赖颜色或图形；Use $frontend-design；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:统计图表选择`、`heading:SCN-STATISTICS-REVIEW-001`）、`personal-bookkeeping-interactive-prototype`（分类明细结构）。
- [ ] 3.4 [ui] 实现 `statistics.loading`、`statistics.empty`、`statistics.income-only` 和 `statistics.error` 状态，分别保持主要结构、隐藏空图表、说明暂无支出、提供重试及去记账/切换月份入口，错误使用可访问 alert；Use $frontend-design；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:State Matrix`、`heading:统计页 page-statistics`、`heading:Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（统计状态和重试交互）。
- [ ] 3.5 [ui] 按现有 `src/shared/styles/tokens.css` 实现 responsive layout、safe-area padding、稳定骨架高度、focus ring、文本溢出、light/dark theme 和 reduced-motion；复用 shared UI，不新增产品级 token 或图表依赖；Use $frontend-design；Inputs: `personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）、`personal-bookkeeping-ux-ui-baseline`（`heading:UI/Visual Foundation`、`heading:Form、反馈与可访问性规则`）。

## 4. 统计行为与交付验证

- [ ] 4.1 [logic] 为 summary、负结余、自然月隔离、未来月份拒绝、分类降序/合计/占比、仅收入和 mutation 刷新补充相邻单元测试；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:SCN-STATISTICS-REVIEW-001`、`heading:OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（统计数据状态）。
- [ ] 4.2 [logic] 为 loading、empty、income-only、error/retry 及跨月来源月/目标月一致性补充状态转换或 query 集成测试，确认错误不展示旧快照；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:State Matrix`、`heading:SCN-STATISTICS-REVIEW-001`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css` 不适用逻辑边界）。
- [ ] 4.3 [ui] 对 375px、768px 和桌面断点检查月份入口、汇总、图表、分类表、底部导航、安全区、文本溢出、focus、loading/empty/error 状态；记录图表与明细的可读性和颜色非唯一依赖；Use $frontend-design；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:UI/Visual Foundation`、`heading:统计图表选择`、`heading:State Matrix`、`heading:SCN-STATISTICS-REVIEW-001`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）。
- [ ] 4.4 [logic] 运行受影响模块相邻测试、项目 `pnpm typecheck` 和必要的 ESLint，记录未执行的全量测试、build、dev server 和浏览器自动化检查；Inputs: `personal-bookkeeping-ux-ui-baseline`（`heading:OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（统计交互验收边界）。
