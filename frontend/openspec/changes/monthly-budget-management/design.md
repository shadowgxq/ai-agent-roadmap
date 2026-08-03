## Context

本 change 为 `page-budget` 建立设备本地当前自然月预算闭环。账单数据由依赖 change `personal-ledger-records` 的统一 ledger domain/repository/query 提供；预算不能复制账单存储或自行定义月份、收入/支出口径。预算页只管理当前自然月，不提供历史月份选择，也不在新自然月自动继承上月预算。

本设计消费以下输入：

| Input ID | Source | Scope |
| --- | --- | --- |
| `personal-bookkeeping-ux-ui-baseline` | `docs/prd/features/01-personal-bookkeeping-ux-ui.md` | `UI/Visual Foundation`、`预算页 page-budget`、`State Matrix`、`Form、反馈与可访问性规则`、`SCN-BUDGET-SET-UPDATE-001`、`OpenSpec Handoff` |
| `personal-bookkeeping-interactive-prototype` | `docs/prd/features/01-personal-bookkeeping-ux-ui.html` | `page-budget` 的预算未设置/已设置结构、设置抽屉、修改、保存失败和进度状态交互 |
| `personal-bookkeeping-design-tokens` | `src/shared/styles/tokens.css` | 页面背景/表面/文字/状态色、间距、圆角、排版、层级、阴影及 light/dark semantic tokens |

## Goals / Non-Goals

**Goals:**

- 保存、读取和覆盖当前自然月预算，定义稳定的预算状态模型及失败恢复边界。
- 从同一 ledger repository/query 计算当前月全部支出作为使用金额，排除收入；账单 mutation 成功后使预算结果重新读取或重算。
- 定义预算金额校验、pending 防重、取消、错误保留输入和错误时不展示未经确认进度的行为。
- 按 UX baseline 和原型实现预算页、设置抽屉、语义状态和现有 token/theme/i18n 约束。

**Non-Goals:**

- 不支持历史月份预算、跨设备同步、账号、云端 API、周期预算或自动沿用预算。
- 不修改 ledger domain/repository/query 的账单 requirements，不改变账单明细或月度汇总口径。
- 不新增产品级视觉 token、第三方依赖或独立的账单存储副本。

## Decisions

### 1. 预算按 `YYYY-MM` 单值存储并覆盖写入

预算 repository 以设备本地月份键 `YYYY-MM` 为唯一定位，记录至少包含月份键、精确金额和更新时间。设置与修改使用同一 upsert/replace 契约；成功后才更新 UI 读模型。选择月份键而非全局单值，是为了让新自然月自然进入 `budget.unset`，也保留未来扩展历史预算的清晰边界；本 change 仍禁止页面选择历史预算。

### 2. 使用金额复用 ledger query 的完整支出口径

预算 query 接收设备本地当前月份和 ledger repository/query，使用该月全部账单中过滤 `type=expense` 的金额求和；不使用当前筛选结果，不把收入抵扣支出，也不从 UI 列表反推。金额在 domain 边界采用两位小数的精确表示进行比较和聚合，避免浮点误差。

### 3. 由已确认数据推导状态

当预算和账单读取均成功时，使用金额为 `spent`，剩余为 `budget - spent`；比例按 `spent / budget * 100` 计算。`<80%` 为正常，`>=80% 且 <100%` 为接近预算，`>=100%` 为达到上限；超支额为 `max(spent - budget, 0)`。未设置预算只展示当前月支出和设置入口，不推导剩余或比例。任一读取失败进入 `budget.error`，清除或隐藏未经确认的进度数据，不复用旧月或旧读数。

### 4. 页面状态与 repository 状态分离

预算 repository 负责本地读取、upsert 和错误归一化；预算 selector 负责由预算记录与 ledger query 结果生成展示模型；页面负责当前月、抽屉草稿、pending、错误反馈和重试编排。提交使用统一 action guard，在 pending 期间禁用保存及关闭导致的重复提交；失败保留草稿和原预算，重试重新执行写入。

### 5. 账单 mutation 通过失效/重算刷新预算

`personal-ledger-records` 的新增、编辑、跨月迁移和删除成功后，预算相关 query/cache 必须重新读取或重算当前自然月。跨月 mutation 至少使来源月和目标月的预算使用结果失效；预算 repository 不监听或修改账单，避免出现双向写入和部分更新。

### 6. UI 复用原型载体和 semantic tokens

预算页保留本月标题、当前月支出、未设置/已设置预算内容、设置/修改入口、进度与状态反馈及底部导航。设置使用语义 dialog/sheet，取消不改变原预算，关闭后焦点回到触发控件。样式只使用 `src/shared/styles/tokens.css` 的既有 semantic tokens；接近预算和超支同时展示状态文字、比例/金额及图标，不只依赖颜色。

## Risks / Trade-offs

- [Risk] ledger repository 与预算 query 形成不同的月份或金额口径。→ Mitigation：预算只调用依赖 change 定义的统一 query/domain，并以相邻测试锁定本地 `YYYY-MM`、expense-only 和精确聚合。
- [Risk] 账单变化后预算页展示缓存的旧使用金额。→ Mitigation：ledger mutation 成功后使来源月/目标月预算 query 失效或重算，pending 期间不提前改变预算结果。
- [Risk] 本地预算读写失败导致用户看到误导性进度。→ Mitigation：统一为可理解的 `budget.error`，不展示未经确认进度；保存失败保留原预算和输入并提供重试。
- [Risk] 超过金额上限或浮点计算造成边界错误。→ Mitigation：在 repository/domain 边界执行金额格式、范围和精确表示校验，并覆盖 `80%`、`100%`、超支及上限场景。
- [Risk] 抽屉和表单在窄屏或键盘操作下遮挡内容。→ Mitigation：复用 shared dialog/sheet，遵循 safe-area、稳定操作区、focus ring、键盘可达和 `aria-invalid`/`aria-describedby` 规则。

## Migration Plan

本 change 没有既有预算数据或外部部署迁移。实现时先建立预算 domain/repository 与 selector，再接入预算页和设置抽屉，最后接入 ledger mutation 的预算 query 失效/重算。若本地存储需要 schema 版本，使用显式版本化迁移；读取或迁移失败进入可重试错误，不以默认金额替代已确认数据。回滚只移除预算页面接入，保留账单数据不变。

## Open Questions

- 实现阶段需确认 `personal-ledger-records` 最终 repository/query 的实际模块路径和现有缓存失效 API，并在不改变本设计契约的前提下接入。
- 实现阶段需确认预算本地存储 adapter 的错误类型和 i18n key 命名；错误语义必须保持可恢复且不泄漏旧进度。
