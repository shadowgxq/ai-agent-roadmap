## Why

轻记账需要让用户在当前自然月内设定一个明确的支出边界，并基于已保存账单可靠地判断使用进度。账单闭环已有统一的数据口径，现在需要补齐预算页的本地预算生命周期、进度状态和可恢复反馈，避免虚构剩余额度或展示过期数据。

## What Changes

- 新增仅针对设备本地当前自然月的预算读取、设置和修改能力。
- 新增预算金额校验：大于 0、最多两位小数且不超过 `9,999,999.99`。
- 基于 `personal-ledger-records` 的同一账单 domain/repository/query 计算当月全部支出使用金额，明确不计收入。
- 新增未设置、正常、接近预算、达到或超支及读取/保存失败状态；进度状态同时使用文字、金额/比例和图标表达。
- 支持保存 pending 防重复提交；保存失败保留输入和原预算并可重试，取消不改变原预算。
- 账单新增、编辑、跨月迁移或删除成功后刷新当前月预算使用结果；新自然月不自动沿用上月预算。

## Capabilities

### New Capabilities

- `monthly-budget`: 管理当前自然月本地预算，并按统一账单口径展示使用、剩余、超支和可恢复状态。

### Modified Capabilities

## Impact

影响预算页 `page-budget`、预算 domain/repository/query 与预算设置抽屉；依赖 `personal-ledger-records` 提供的账单 domain、repository 和月度支出查询口径。实现沿用现有 theme、i18n、shared UI 与 `src/shared/styles/tokens.css`，不引入外部 API 或新的产品级设计 token。
