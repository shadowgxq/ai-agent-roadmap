## Context

本 change 交付 `page-ledger` 与 `page-entry` 的本地账单闭环：按自然月浏览、汇总、筛选，以及新增、编辑、跨月迁移和删除。当前仓库只有模板基座，已提供 React Router、`@tanstack/react-query`、Radix primitives、`lucide-react`、theme 和 i18n；没有账单 domain、repository 或 storage adapter。产品没有账号、云同步或外部账单 API，账单是预算和统计的共同数据源，因此账单读模型和 mutation 结果必须成为可复用的一致数据边界。

本设计消费的输入如下，表内范围是本 change 的约束，不把交互原型直接当作生产页面：

| Input ID | Source | Scope |
| --- | --- | --- |
| `personal-bookkeeping-ux-ui-baseline` | `docs/prd/features/01-personal-bookkeeping-ux-ui.md` | `Page Inventory`；`信息架构与全局 UI`；`UI/Visual Foundation`；账单页 `page-ledger`；记一笔页 `page-entry`；`State Matrix`；`Form、反馈与可访问性规则`；`SCN-LEDGER-FIRST-001`；`SCN-LEDGER-EDIT-FILTER-001`；`OpenSpec Handoff` |
| `personal-bookkeeping-interactive-prototype` | `docs/prd/features/01-personal-bookkeeping-ux-ui.html` | `page-ledger`/`page-entry` 的结构，以及月份选择、筛选、loading/empty/error、保存/删除 pending、删除确认和放弃更改确认的交互载体 |
| `personal-bookkeeping-design-tokens` | `src/shared/styles/tokens.css` | 现有 spacing、radius、typography、z-index、shadow 和 light/dark semantic color tokens；禁止新增产品级 token |

原始业务 requirement 的覆盖边界如下：`req-ledger-monthly-browsing` 与 `req-ledger-filter-and-states` 由 `ledger-browsing-filtering` 覆盖；`req-entry-create-and-edit` 与 `req-entry-validation-and-recovery` 由 `ledger-entry-lifecycle` 覆盖；`req-entry-delete-and-persistence` 由 `ledger-entry-lifecycle` 与 `ledger-persistence-consistency` 共同覆盖。预算和统计只消费本 change 的一致账单数据，不在本 change 新增它们的页面或业务功能。

实现阶段仍需遵守 `docs/frontend/standards/frontend-development.md`、`docs/frontend/standards/accessibility-and-ui-states.md`、`docs/frontend/components/components.md`、`docs/frontend/components/component-splitting.md`、`docs/frontend/standards/file-organization.md` 和 `docs/frontend/guides/theming-and-i18n.md`。

## Goals / Non-Goals

**Goals:**

- 建立带稳定 ID、交易日期、创建时间和固定分类的账单 domain 与本地持久化边界。
- 按自然月从完整账单集合计算汇总、日期分组、日小计和筛选列表，并区分可恢复页面状态。
- 保证新增、覆盖编辑、跨月迁移和删除的成功结果一致，失败不产生部分更新。
- 为表单提供可恢复的 validation、pending、success、error、delete-confirm 和 discard-confirm 状态。
- 让账单页面遵循现有 shared UI、theme、i18n 和 `src/shared/styles/tokens.css`，在移动端保持稳定入口与可访问性。

**Non-Goals:**

- 不实现预算、统计页面的新功能；只保留同一账单 repository/query 数据源和可失效边界供消费者使用。
- 不实现账号、云同步、多账本、导入导出、自定义分类、周期记账或外部 API。
- 不重新设计产品级视觉系统，不新增设计 token 或第三方依赖。
- 不把原型中的检查面板、示例数据或演示状态机带入生产页面。

## Decisions

### 1. 账单 domain、分类和金额表示

账单 domain 至少包含：

- `id`：稳定且唯一；编辑时保持不变。
- `type`：`income` 或 `expense`。
- `amountCents`：大于 0 的整数，范围为 1 至 `999999999`，对应展示上限 `9,999,999.99`。
- `category`：当前 `type` 下的固定分类值。
- `date`：本地日历日期字符串 `YYYY-MM-DD`，不能晚于设备本地当前日期。
- `note`：保存时 trim 后的可选备注，最多 50 个字符。
- `createdAt`：创建时生成的 epoch milliseconds；编辑不改变它。

固定分类直接来自业务 requirement：支出为 `餐饮`、`交通`、`购物`、`居住`、`娱乐`、`医疗`、`其他`；收入为 `工资`、`奖金`、`理财`、`其他`。两个类型的“其他”是不同的 domain 值，筛选条件不能只用无类型的显示文字区分它们。

金额在 domain/storage 边界使用 integer cents，UI 输入和展示在边界处转换为人民币两位小数。选择 integer cents 是为了避免 JavaScript floating-point 聚合误差；直接使用 number 元值会让金额上限、负结余和跨月汇总在边界情况下不稳定，使用 decimal string 则会把解析和比较逻辑散落到每个消费者。日期使用 calendar string 而不是 `Date` 对象，避免 UTC 转换改变本地月份归属；同日排序使用 `createdAt`，相同时用 `id` 作确定性 tie-breaker。

### 2. Repository、版本化存储和原子 mutation

使用 feature-scoped repository 隔离 UI 与 Web Storage。repository 对外提供读取全部记录、按 ID 读取、创建、覆盖编辑和删除；调用方只接收 domain record 或结构化的可恢复错误，不接收未经校验的 persisted JSON。存储使用一个带 `schemaVersion` 的账单快照 envelope，读入时校验 envelope、每个字段、类型/分类关系、金额范围和日期格式；无效数据按读取错误处理，不能静默清空或拼接部分记录。

每次 mutation 都基于已确认快照构造完整的 next snapshot，序列化后执行一次 adapter commit；commit 失败时不更新 query/cache，也不改变原记录。编辑按原 `id` 覆盖并保留 `createdAt`，删除只移除目标 ID，所有受影响月份从成功后的完整集合重新派生。这样跨月编辑天然同时更新来源月和目标月，不需要维护两份月度汇总。

选用单快照 adapter 是因为本期账单数据量小且需要原子替换；分散的逐条 key 写入会暴露部分更新窗口，client UI store 也不能替代持久化。若未来数据量需要 IndexedDB，可替换 adapter，不改变 repository 与 selector 契约。

### 3. Query、selector 和状态 ownership

账单 query 以稳定、可序列化的 base key 读取完整已确认账单集合，例如 `['ledger-records']`；月份、类型和分类是 selector 输入，不复制成多个可互相漂移的 client store。selector 负责：

1. 以本地 `date` 计算月份归属和完整收入/支出/结余；
2. 按交易日期倒序分组、同日按 `createdAt` 倒序并计算筛选后的收入/支出日小计；
3. 生成当前类型允许的分类选项，并在类型切换时清除不再适用的分类；
4. 对所有金额格式化为两位小数，顶部月度汇总始终使用未筛选集合。

`page-ledger` 的月份、类型、分类和可恢复导航状态放在 URL search params，以便返回和刷新时可恢复；不存在或不合法的筛选回退到 `all`，未来月份不能成为有效选择。表单草稿、字段错误、dirty、dialog、pending 和 mutation error 属于 `page-entry`/对应 feature model 的局部 state，不写入全局 UI store。repository/query 数据由 React Query 管理，保存或删除成功后明确 invalidate 或更新 base query，并让预算/统计消费者从同一 domain 数据源重新读取。

读取处于 `isLoading` 时显示稳定骨架；读取失败时，即使 React Query 保留了上一次 `data`，渲染层也必须以 `isError` 为准隐藏汇总和列表，避免旧月份数据冒充当前结果。重试成功后才重新显示已确认数据。

### 4. Entry、Data Flow 和 mutation 返回

入口与数据流固定为：

1. `page-ledger` 读取 base query，使用 selector 得到完整汇总和当前筛选列表；点击稳定的 `记一笔` 或账单行后进入 `page-entry`，编辑入口携带记录 ID。
2. `page-entry` 从 ID 读取并完整映射为局部草稿；新增草稿初始化为 `expense`、本地当前日期、空分类、空金额和空备注。
3. 用户动作只通过统一的 form submit/delete action guard 触发校验和 repository mutation；成功前不提前改变账单、汇总、预算或统计。
4. mutation 成功后使 ledger base query 失效，按记录交易日期月份定位账单页，并通过不抢焦点的 `aria-live`/toast 提供短反馈；失败留在表单，保留完整草稿并提供重试。

跨月编辑必须让来源月和新月份都从成功的完整集合重新计算。预算与统计页面不在此处实现，但它们必须能通过同一账单数据源读取最新结果；当前仓库不存在这些消费者时，不新增占位页面，只保留明确的 query/repository 边界。

### 5. Interaction Flow 和 stable UI boundaries

稳定的页面边界为：

- app shell/bottom navigation：账单、预算、统计三项导航；账单页主动作位置在加载、月份切换、空态、错误和筛选切换时保持可发现。
- `page-ledger`：月份触发器、月度汇总、筛选工具栏、日期组列表、记录行和状态视图；筛选抽屉关闭时未应用的草稿不改变列表。
- `page-entry`：全屏返回/标题壳层、类型切换、金额、分类、日期、备注、保存操作区和编辑态删除入口；新增不显示删除。
- overlay：月份选择使用 sheet/dialog，筛选使用 sheet，删除和放弃使用语义 dialog；打开时焦点进入前景，关闭或取消后回到触发控件。

月度选择只允许当前月和有账单的历史月，未来月在控件中禁用或拒绝；用户仍可回到当前月。`ledger.empty.month` 作为无记录历史月的防御性状态保留，具体何时向用户展示任意无账单历史月见 Open Questions。列表记录必须显示分类、备注（无备注时有明确替代文本）、金额以及收入/支出文字或图标；普通支出不用危险色。

所有可见文案走现有 i18n，所有颜色和尺寸使用现有 semantic/primitive tokens，使用 Lucide 图标和 shared/Radix primitives；触控区域至少 `44px`，固定底部导航/表单操作区预留 safe-area，错误与 pending 同时提供可见文字和合适 live region，并尊重 `prefers-reduced-motion`。

### 6. UI component boundaries

route page entry 只负责路由参数、状态归属和页面级组合。账单列表的日期组、筛选工具栏、状态视图和表单字段组在首次实现时按 page-private 或 feature 语义就近放置；只有无业务语义且有稳定复用价值的基础控件进入 `shared/ui`。query、selector、repository、mutation 和错误归一化放入拥有该语义的 `model`/`api` 边界，展示组件不直接创建 request client 或读写 storage。

## Risks / Trade-offs

- [Risk] Web Storage 读写、配额或 persisted payload 损坏会阻断账单读取。→ [Mitigation] 使用版本化 envelope 和字段校验；错误结构化返回，保留原始存储，不用空集合或旧 query data 冒充成功，并提供页面重试。
- [Risk] React Query 在 refetch error 时可能保留旧 `data`。→ [Mitigation] 页面以当前 query 的 `isError` 优先级渲染错误状态，并覆盖汇总、列表和日期小计。
- [Risk] 跨月编辑或删除只失效当前视图会造成消费者不一致。→ [Mitigation] mutation 只更新完整 base snapshot，成功后统一失效 base query；相关消费者从同一 domain source 重新计算。
- [Risk] URL 中的月份/筛选参数可能与本地账单不匹配。→ [Mitigation] 参数通过 typed parser 收窄，未知/未来值回退到安全默认，筛选条件只由 selector 解释。
- [Risk] 自定义抽屉和确认框带来焦点、键盘和触控缺陷。→ [Mitigation] 优先使用现有 shared/Radix primitives 和原生控件，按 accessibility 与 UI states 规范验证。

## Migration Plan

本 change 没有既有账单 schema 或外部部署迁移。实现顺序为：

1. 建立 domain types/constants、金额与日期工具、versioned storage envelope 和 repository。
2. 建立纯 selector、query/mutation 状态和失败归一化；先让账单数据路径可测试。
3. 接入 `page-ledger` 和 `page-entry`，再接通 success/error/pending/confirm 状态与返回月份定位。
4. 统一 invalidate/re-read 边界，供预算/统计后续 change 消费；不在本 change 增加预算/统计页面。

首次没有账单时从空集合开始。发现缺失或无效 schema 时返回可恢复错误，不自动删除用户原始数据；未来若 schema 版本升级，迁移必须先生成新快照、提交成功后再让 query 失效，失败则保留旧快照。

## Open Questions

- 原始 PRD 的月度浏览要求强调“只能切换到有账单的历史月份”，但同一需求和 UX `State Matrix` 又要求展示“历史月份无账单”状态；当前采用“月份选择器只列当前月/已知有账单历史月，`ledger.empty.month` 作为删除最后一笔、URL 保留或数据变化后的防御状态”的实现假设。产品需要在实现验收前确认是否允许直接选择任意过去月份；这不阻塞账单 domain 和现有场景实现。
- 预算与统计页面当前不在仓库中，后续 change 需要确认它们消费 ledger base query 的具体公开出口和 cache key；本 change 只保证 repository/domain source 一致，不预先实现这些页面。
