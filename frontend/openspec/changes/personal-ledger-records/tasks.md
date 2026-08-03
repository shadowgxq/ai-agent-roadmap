## 1. 账单 domain 与本地持久化

- [x] 1.1 [logic] 建立账单 domain types/constants：稳定 `id`、`type`、integer cents 金额、`YYYY-MM-DD` 交易日期、不可变 `createdAt`、trim 后备注，以及支出/收入固定分类清单；关联 requirements `req-ledger-monthly-browsing`、`req-entry-create-and-edit`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`记一笔页 page-entry`、`Form、反馈与可访问性规则`）。
- [x] 1.2 [logic] 实现金额、有效本地日历日期、未来日期、备注长度、类型/分类关系和 `YYYY-MM` 月份归属校验，统一输入/存储/两位小数展示之间的转换；关联 requirements `req-ledger-monthly-browsing`、`req-entry-validation-and-recovery`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`UI/Visual Foundation`、`记一笔页 page-entry`）。
- [x] 1.3 [logic] 实现带 `schemaVersion` 的本地账单快照、字段校验和结构化读写错误归一化；无效或损坏 payload 不得静默清空、部分恢复或回退为旧成功数据；关联 requirement `req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`OpenSpec Handoff`）、`personal-bookkeeping-interactive-prototype`（读取错误/重试状态）。
- [x] 1.4 [logic] 实现 repository CRUD：创建生成稳定 ID/创建时间，编辑按原 ID 覆盖且保留 `createdAt`，删除只移除目标 ID；使用单快照 commit 保证写入失败时原记录不变；关联 requirements `req-entry-create-and-edit`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`SCN-LEDGER-FIRST-001`、`SCN-LEDGER-EDIT-FILTER-001`、`OpenSpec Handoff`）。

## 2. 查询、汇总与 mutation 状态

- [x] 2.1 [logic] 实现纯 selector：按本地交易日期归属自然月，计算完整收入/支出/负结余，按日期和创建时间倒序分组，计算筛选后的收入/支出日小计，并保证所有金额为两位小数展示；关联 requirement `req-ledger-monthly-browsing`；Inputs: `personal-bookkeeping-ux-ui-baseline`（账单页 `page-ledger`、`SCN-LEDGER-EDIT-FILTER-001`）。
- [x] 2.2 [logic] 实现全部/收入/支出及类型对应分类筛选，类型切换清除不匹配分类并区分两类同名“其他”，筛选只改变列表和日小计不改变顶部汇总；关联 requirement `req-ledger-filter-and-states`；Inputs: `personal-bookkeeping-ux-ui-baseline`（账单页 `page-ledger`、`SCN-LEDGER-EDIT-FILTER-001`）、`personal-bookkeeping-interactive-prototype`（筛选抽屉交互）。
- [x] 2.3 [logic] 接入稳定 query key 和 query/mutation 状态，区分 loading、首次设备空、历史月空、筛选空、读取 error 和 mutation error；读取失败时隐藏旧汇总/列表并支持重试；关联 requirement `req-ledger-filter-and-states`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（状态交互）。
- [x] 2.4 [logic] 完成保存/删除成功后的 base query invalidation、来源月/新月份定位和同一账单数据源的消费者刷新边界；不新增预算或统计页面；关联 requirements `req-entry-create-and-edit`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`SCN-LEDGER-FIRST-001`、`SCN-LEDGER-EDIT-FILTER-001`、`OpenSpec Handoff`）。
- [x] 2.5 [logic] 为金额边界、负结余、有效日期、排序、日小计、类型/分类清除、覆盖不重复、跨月迁移、读取错误隔离和 mutation 失败无部分更新补充相邻单元测试；关联 requirements `req-ledger-monthly-browsing`、`req-ledger-filter-and-states`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、两个 Scenario Registry 场景）。

## 3. 账单页 `page-ledger`

- [x] 3.1 [ui] 实现 page-ledger 的 route-level composition、底部三项导航、月份触发器、当前月回退和始终稳定的“记一笔”主入口，复用 shared/Radix dialog/sheet 和 Lucide 图标；Use $frontend-design；关联 requirement `req-ledger-monthly-browsing`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`Page Inventory`、`信息架构与全局 UI`、账单页 `page-ledger`）、`personal-bookkeeping-interactive-prototype`（月份选择交互）。
- [x] 3.2 [ui] 实现收入/支出/结余汇总、日期分组账单行、日小计、创建时间排序、收入/支出文字与图标差异及记录编辑入口；Use $frontend-design；关联 requirements `req-ledger-monthly-browsing`、`req-entry-create-and-edit`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`UI/Visual Foundation`、账单页 `page-ledger`、`SCN-LEDGER-FIRST-001`）。
- [x] 3.3 [ui] 实现全部/收入/支出 segmented control、类型对应分类筛选、已应用条件表达和一键重置，保证筛选无结果时保留上下文且汇总不变；Use $frontend-design；关联 requirement `req-ledger-filter-and-states`；Inputs: `personal-bookkeeping-ux-ui-baseline`（账单页 `page-ledger`、`SCN-LEDGER-EDIT-FILTER-001`）、`personal-bookkeeping-interactive-prototype`（筛选抽屉交互）。
- [x] 3.4 [ui] 实现 loading、首次设备空、历史月空、筛选空和读取 error 状态，错误状态提供可恢复重试且不显示过期汇总；Use $frontend-design；关联 requirement `req-ledger-filter-and-states`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（状态检查对应结构）。
- [x] 3.5 [ui] 按现有 tokens 实现 responsive layout、safe-area padding、稳定尺寸、focus ring、文本溢出、light/dark、`prefers-reduced-motion` 和 i18n 文案；普通支出不使用危险色；Use $frontend-design；关联 requirements `req-ledger-monthly-browsing`、`req-ledger-filter-and-states`；Inputs: `personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）、`personal-bookkeeping-ux-ui-baseline`（`UI/Visual Foundation`、`信息架构与全局 UI`）。

## 4. 记一笔页 `page-entry`

- [x] 4.1 [ui] 实现全屏新增/编辑表单壳层、返回、支出/收入切换、金额、固定分类、交易日期、备注及仅编辑态显示的删除入口；Use $frontend-design；关联 requirements `req-entry-create-and-edit`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`Page Inventory`、`记一笔页 page-entry`）、`personal-bookkeeping-interactive-prototype`（表单/删除交互）。
- [x] 4.2 [logic] 实现新增默认值、编辑预填、局部草稿、类型切换清空分类、dirty 判断、成功按交易日期月份返回和失败保留全部输入；关联 requirements `req-entry-create-and-edit`、`req-entry-validation-and-recovery`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`SCN-LEDGER-FIRST-001`、`SCN-LEDGER-EDIT-FILTER-001`）。
- [x] 4.3 [ui] 实现 blur/submit 字段级校验、`aria-invalid`/`aria-describedby`、错误 live region、首错聚焦和键盘可达顺序；Use $frontend-design；关联 requirement `req-entry-validation-and-recovery`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（表单状态交互）。
- [x] 4.4 [ui] 实现保存 pending 防重复、删除 pending、不可恢复删除确认、未保存离开确认、Escape/取消和关闭后焦点回归，并提供成功/失败的可见与非阻塞 live feedback；Use $frontend-design；关联 requirements `req-entry-validation-and-recovery`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`信息架构与全局 UI`、`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-interactive-prototype`（删除/放弃确认交互）。

## 5. 场景验证与交付

- [x] 5.1 [logic] 为 `SCN-LEDGER-FIRST-001` 和 `SCN-LEDGER-EDIT-FILTER-001` 补充或更新相邻行为测试，覆盖首次空、新增、编辑覆盖、跨月、筛选、删除确认/失败重试、重复提交、失败无部分更新和刷新恢复；关联 requirements `req-ledger-monthly-browsing`、`req-ledger-filter-and-states`、`req-entry-create-and-edit`、`req-entry-validation-and-recovery`、`req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（两个 Scenario Registry 场景、`OpenSpec Handoff`）。
- [x] 5.2 [logic] 对 repository/query/selector 与受影响消费者执行目标模块测试、项目 `pnpm typecheck` 和必要的 ESLint，记录未运行的全量测试、build、dev server 和浏览器自动化检查；关联 requirements `req-entry-delete-and-persistence`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`OpenSpec Handoff`）。
- [ ] 5.3 [ui] 在获准的交互/视觉验证中检查 375px、768px 和桌面布局的主入口稳定位置、底部导航与 safe area、文本不溢出、focus、loading/empty/error/pending/confirm 状态及 light/dark token 使用；Use $frontend-design；关联 requirements `req-ledger-filter-and-states`、`req-entry-validation-and-recovery`；Inputs: `personal-bookkeeping-ux-ui-baseline`（`State Matrix`、`Form、反馈与可访问性规则`）、`personal-bookkeeping-design-tokens`（`src/shared/styles/tokens.css`）。
