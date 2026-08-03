## Why

轻记账需要一个可独立验收的本地账单闭环，让用户能在首次使用时快速记下一笔，并按自然月可靠浏览、筛选、修改和删除记录。当前 UX baseline、交互原型和业务需求已经明确了状态、校验、恢复及汇总口径，现在需要把这些用户可观察行为固化为实现契约。

## What Changes

- 新增当前月默认、历史月切换和禁止未来月份的账单浏览能力。
- 新增按收入/支出/全部及对应分类筛选的账单列表，并区分首次空、历史月空、筛选无结果和读取错误状态。
- 新增账单记录表单，支持支出/收入、金额、固定分类、交易日期和备注的新增与编辑。
- 新增编辑态删除、不可恢复二次确认、保存/删除 pending 防重、失败重试和未保存离开确认。
- 保证新增、覆盖编辑、跨月迁移和删除对相关月份的汇总结果一致，并在本地设备持久化。

## Capabilities

### New Capabilities

- `ledger-browsing-filtering`: 按自然月查看账单汇总、倒序明细分组、收入/支出/分类筛选及可恢复页面状态。
- `ledger-entry-lifecycle`: 新增、编辑、跨月修改和删除单笔账单，以及表单校验、反馈和离开保护。
- `ledger-persistence-consistency`: 本地账单的持久化、覆盖写入和原子更新，保证新增、编辑、迁移、删除后的月度汇总一致。

### Modified Capabilities

## Impact

影响账单页 `page-ledger`、记一笔页 `page-entry`、共享账单 domain/model 与本地 storage/query 边界；预算和统计会消费同一账单数据口径并在账单变更后重新计算。UI 复用现有 shared UI、theme、i18n 和 `src/shared/styles/tokens.css`，不引入新的外部 API 或产品级视觉系统。
