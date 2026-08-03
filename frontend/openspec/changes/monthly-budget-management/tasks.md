## 1. 预算 domain 与本地持久化

- [ ] 1.1 [logic] 建立当前自然月预算类型、`YYYY-MM` 月份键、精确金额表示与大于 0/最多两位小数/`9,999,999.99` 上限校验；关联 `personal-bookkeeping-ux-ui-baseline`（`预算页 page-budget`、`Form、反馈与可访问性规则`、`SCN-BUDGET-SET-UPDATE-001`）。
- [ ] 1.2 [logic] 实现预算 repository/storage adapter 的当前月读取与 upsert/覆盖写入，区分未设置和读取/保存错误，不自动继承上月预算；关联 `personal-bookkeeping-ux-ui-baseline`（`OpenSpec Handoff`、`State Matrix`）、`personal-bookkeeping-interactive-prototype`（预算设置/修改交互）。
- [ ] 1.3 [logic] 归一化预算读写失败并定义保存 pending、防重复提交、失败保留输入与原预算的 action 状态契约；关联 `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（保存失败重试交互）。

## 2. 账单消费与预算进度

- [ ] 2.1 [logic] 接入 `personal-ledger-records` 的账单 domain/repository/query，按当前本地自然月查询全部账单并仅聚合 `expense`，不受账单页筛选影响；关联 `personal-bookkeeping-ux-ui-baseline`（`预算页 page-budget`、`OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（预算页支出展示）。
- [ ] 2.2 [logic] 实现未设置、正常、接近预算、达到/超支和错误的预算 selector，覆盖 `<80%`、`>=80% && <100%`、`>=100%`、剩余和超出金额边界；关联 `personal-bookkeeping-ux-ui-baseline`（`预算页 page-budget`、`State Matrix`、`SCN-BUDGET-SET-UPDATE-001`）。
- [ ] 2.3 [logic] 接入账单新增、编辑、跨月迁移和删除成功后的预算 query 失效或重算，至少刷新来源月和目标月，不提前改变未确认结果；关联 `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（预算进度更新交互）。
- [ ] 2.4 [logic] 为金额校验与精确聚合、收入排除、阈值边界、未设置新月份、跨月刷新、读取失败不复用旧数据和保存失败恢复补充相邻单元测试；关联 `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`SCN-BUDGET-SET-UPDATE-001`）、`personal-bookkeeping-design-tokens`（逻辑不改变 token 契约）。

## 3. 预算页与设置交互

- [ ] 3.1 [ui] 实现 `page-budget` 当前月标题、本月支出、未设置预算状态及设置入口，保持底部导航和主要操作位置稳定；Use $frontend-design；关联 `personal-bookkeeping-ux-ui-baseline`（`预算页 page-budget`、`UI/Visual Foundation`）、`personal-bookkeeping-interactive-prototype`（`page-budget` 结构）。
- [ ] 3.2 [ui] 实现已设置预算的金额、已使用、剩余、比例/进度、正常/接近/达到或超支状态，使用文字、图标和金额结构表达而非仅依赖颜色；Use $frontend-design；关联 `personal-bookkeeping-ux-ui-baseline`（`预算页 page-budget`、`State Matrix`、`UI/Visual Foundation`）、`personal-bookkeeping-interactive-prototype`（已设置预算状态）。
- [ ] 3.3 [ui] 实现预算设置/修改底部抽屉，支持原预算初始化、金额字段级校验、取消不变更、保存中禁用和失败后输入保留及重试；Use $frontend-design；关联 `personal-bookkeeping-ux-ui-baseline`（`Form、反馈与可访问性规则`、`SCN-BUDGET-SET-UPDATE-001`、`State Matrix`）、`personal-bookkeeping-interactive-prototype`（设置抽屉、保存失败交互）。
- [ ] 3.4 [ui] 接入预算 loading、unset、error 和成功反馈状态，读取错误不展示旧进度；为 dialog/sheet 实现语义角色、焦点进入/回归、Escape/取消、`aria-invalid`/`aria-describedby` 和键盘可达顺序；Use $frontend-design；关联 `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（错误与关闭交互）。
- [ ] 3.5 [ui] 使用 `src/shared/styles/tokens.css` 的现有 semantic tokens 实现 light/dark、safe-area、稳定布局、focus ring、文本溢出和响应式预算页，不新增产品级 token；Use $frontend-design；关联 `personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）、`personal-bookkeeping-ux-ui-baseline`（`UI/Visual Foundation`、`预算页 page-budget`）。

## 4. 验证与交付

- [ ] 4.1 [logic] 为 `SCN-BUDGET-SET-UPDATE-001` 补充或更新相邻测试，覆盖首次设置、修改、取消、pending 防重、失败重试、账单变化重算和超支金额；关联 `personal-bookkeeping-ux-ui-baseline`（`SCN-BUDGET-SET-UPDATE-001`、`OpenSpec Handoff`）。
- [ ] 4.2 [ui] 检查 375px、768px 和桌面布局下预算进度、抽屉、错误/空/保存中状态、focus、safe-area、文本不溢出及底部导航；Use $frontend-design；关联 `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`、`预算页 page-budget`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）。
- [ ] 4.3 [logic] 运行受影响模块的相邻测试、项目 `pnpm typecheck` 和必要的 ESLint，记录未运行的全量测试、build、dev server 和浏览器自动化检查；关联 `personal-bookkeeping-ux-ui-baseline`（`OpenSpec Handoff`）。
