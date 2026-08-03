## Why

用户需要在记账后快速回答本月花在哪里、收入支出差额是多少，但当前账单数据还没有一个统一的统计复盘入口。现在补齐统计页，可以在复用账单 domain/repository/query 的前提下，把自然月汇总、支出分类分布和可恢复状态固化为可验收契约。

## What Changes

- 新增统计页，默认展示当前自然月，并允许切换到有账单历史月份，禁止未来月份。
- 按所选月份全部账单计算收入、支出和结余，金额保留两位小数，结余允许为负，并与账单页保持一致。
- 新增仅针对支出的固定分类 breakdown，按金额降序展示水平条形图和精确明细列表，分类合计等于支出总额，占比显示一位小数。
- 新增无账单、仅收入、读取中和读取失败状态；空/错状态提供切换月份、去记账或重试等下一步，失败时不以其他月份或旧数据替代。
- 账单新增、编辑、删除和跨月迁移后，重新计算所有受影响月份的统计结果。

## Capabilities

### New Capabilities

- `monthly-spending-statistics`: 提供自然月收支汇总、支出分类 breakdown、月份切换和可恢复统计页状态。

### Modified Capabilities

## Impact

影响统计页、统一 ledger domain/repository/query 的消费边界、月份查询和账单 mutation 后的派生数据刷新；不新增外部 API、账户体系或独立统计数据源。UI 沿用现有 shared UI、theme、i18n 和 `src/shared/styles/tokens.css`。
