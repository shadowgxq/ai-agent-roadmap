# Repair Pipeline

`repairs/` 是项目级修复队列，用于处理小范围、可独立验证的 repair item，不与 `manager/plan.yaml` 或 OpenSpec 批次混在一起。

该队列是文档驱动的，v1 不包含后台 runner。只有用户显式调用 `$repair-intake` 时，才进入自然语言问题登记流程；修复执行、用户验证和归档由 `$repair-runner` 或外部 goal 循环重复调用完成。

## 目录结构

```text
repairs/
  README.md
  list.yaml
  repair-template.md
  queue/
    repair-*.md
  archive/
    YYYY-MM-DD-repair-*.md
```

活动 repair 文件放在 `queue/`。文件中的 YAML `status` 字段表示当前阶段：

| Status       | 含义                                       |
| ------------ | ------------------------------------------ |
| `todo`       | 可以被领取处理。                           |
| `processing` | 已被 coordinator 或 worker 领取。          |
| `fixed`      | agent 修复和工程验证已完成，等待用户验证。 |
| `verified`   | 用户已确认修复结果，等待明确归档。         |
| `blocked`    | 缺少信息、决策或外部状态，暂时无法完成。   |
| `archived`   | 已关闭的历史记录，保存在 `archive/`。      |

## Repair 文件规则

- 每个 repair item 使用一个 Markdown 文件。
- 文件名使用稳定 id：`repair-YYYYMMDD-NNN.md`。
- 从 `repair-template.md` 创建新文件，并放到 `queue/`。
- 不要把多个 repair item 写到同一个文件。
- 复现步骤和验证证据写在 repair 文件内。
- 截图、日志、issue 链接或用户提供的来源写入 `source`。
- 本轮执行范围、运行中修复项、已修复待用户验证、已验证待归档和本轮归档记录写入 `list.yaml`。
- 如果 repair item 会改变产品行为、API 契约、schema 或 shared OpenSpec 意图，应升级到 Manager/OpenSpec 流程，而不是作为纯 repair 处理。

## 状态机

正常路径：

```text
todo -> processing -> fixed -> verified -> archived
```

阻塞路径：

```text
todo -> processing -> blocked
```

恢复路径：

```text
blocked -> todo
```

只有用户明确验证通过后，才把 `fixed` 改成 `verified`。只有用户明确要求归档、清理或 prune 已验证 repair item 时，才把 `verified` repair item 从 `queue/` 移到 `archive/`。自动化循环中不要隐式归档。

## Ready 标准

Ready 标准分为必填、推荐和可选。缺少推荐项不应阻塞整个队列；runner 可以先基于现有信息修复，或者只把信息不足的单个 repair item 标记为 `blocked` 后继续处理其它修复项。

必填：

- `id`、`status`、`created_at`、`updated_at`。
- `source` 或 `Actual` 至少有一项能说明用户报告、截图、日志、issue 或现象。

推荐：

- `Repro` 写出复现路径。
- `Expected` 写出期望行为；不明确时可由 agent 在 `Notes` 写明推断和 assumptions。
- `scope` 写明可改文件或模块。
- `Verification` 或 `Notes` 写明自动验证命令或 manual verification。

可选：

- `scope` 可以写 `unknown`；runner 默认串行。
- 验证方式可以是 manual。
- `regression_test` 可以是 `not_applicable`，修复后再由 runner 更新。

如果问题会改变产品行为、API 契约、schema 或 shared OpenSpec 意图，应升级到 Manager/OpenSpec 流程，不进入 repair 自动队列。

## 执行流程

推荐路径：

1. 用户显式调用 `$repair-intake` 并描述问题，`$repair-intake` 先判断描述是否足够清楚。
2. 如果描述不足以满足必填规范，`$repair-intake` 追问用户补充；符合规范后才创建 repair 文件。
3. `$repair-intake` 做只读轻量代码定位，尽量推断 `scope`；无法快速定位时写 `scope: unknown`，并把搜索证据和 assumptions 写入 `Notes`。
4. `$repair-intake` 创建 `queue/repair-*.md`，并加入 `list.yaml.selected.files`。
5. 用户启动 `/goal`，目标中指定 `$repair-runner`，或直接要求 `$repair-runner` 处理当前 list。
6. `$repair-runner` 读取 `list.yaml`；如果 `selected.files` 非空，则只处理这些文件，否则按用户指定文件或 `queue/*.md` 生成本轮选择范围。
7. `$repair-runner` 运行只读校验，展示 queue preview，并回写 `list.yaml` 的 `selected.files` 和 `current_run`。
8. `$repair-runner` 最多选择 3 个互不冲突的 repair item，设置为 `processing`，并回写单个 repair 文件和 `list.yaml`。
9. `$repair-runner` 为每个 repair item 分发一个 worker subagent；worker 只修自己的 repair item，不修改 `repairs/**`。
10. `$repair-runner` 验收 worker 输出，运行相关检查，把成功项标记为 `fixed`，写入 `list.yaml` 的 `fixed_waiting_user_verification`。
11. 用户验证通过后，明确要求标记 verified；`$repair-runner` 把对应 repair item 改成 `verified`，并移入 `list.yaml` 的 `verified_waiting_archive`。
12. 用户明确要求 archive/prune/清理后，`$repair-runner` 把 `verified` repair item 移到 `archive/YYYY-MM-DD-repair-*.md`，更新状态为 `archived`，并在 `list.yaml` 记录归档结果。

## Goal 使用方案

`/goal` 只作为外层循环，重复调用 `$repair-runner`。repair 文件 list、串并行判断、worker 派发、验证、`list.yaml` 和单个 repair 文件回写仍由 skill 负责。

推荐目标描述：

```text
循环执行当前项目的 `$repair-runner`。

本次只处理以下 repair 文件：
- repairs/queue/repair-YYYYMMDD-001.md
- repairs/queue/repair-YYYYMMDD-002.md

每轮由该 skill 读取 `repairs/list.yaml` 和指定 repair 文件 list，解析 YAML status，选择可执行的 `status: todo` repair item，按 skill 规则判断串行或并行，最多并行 3 个 worker subagent，执行修复、验证和状态回写。若我没有指定文件 list 且 `list.yaml.selected.files` 为空，才扫描 `repairs/queue/*.md`。

当该 skill 展示 queue preview 时，视为我已确认处理 `status: todo` repair item，直接继续；但不授权用户验证确认或归档，`verified` repair item 只有在我明确要求 archive/prune/清理时才能移动到 `repairs/archive/`。

每轮结束后重新读取指定 repair 文件和 `repairs/list.yaml`。持续执行直到指定范围内没有可自动执行的 `status: todo` repair item；如果只剩 `fixed`、`verified` 或 `blocked`，停止并汇报队列状态。

不要执行 `git add`、`git commit`、`git push`、deploy、publish 或自动 archive。
```

Goal 循环规则：

- 每轮必须重新读取指定 repair 文件和 `list.yaml`，不要复用上一轮缓存。
- preview 预授权只适用于领取和修复 `todo` repair item，不适用于用户验证确认或 archive。
- 没有可执行 `todo` 时可以结束 goal；如果仍有 `fixed`、`verified` 或 `blocked`，最终汇报必须说明它们分别等待用户验证、归档确认或人工处理。
- 已存在 `processing` 时，只有能确认是当前中断 run 且工作区现场安全，才继续处理；否则停止并标记或汇报阻塞。

## Processing 恢复规则

`processing` 应写入 `claimed_by`、`claimed_at` 和 `run_id`，用于处理中断恢复：

- `run_id` 匹配 `list.yaml` 的当前 run，且相关改动现场清晰时，可以继续。
- `claimed_at` 为空，或无法判断领取来源时，停止并记录 blocker。
- `run_id` 不匹配且无法确认现场安全时，不要强行接管。
- 人工确认后，可以把可恢复的 `blocked` 或 stale `processing` 改回 `todo`。

## Worker 约束

Worker 必须：

- 只读取并处理分配给自己的一个 repair 文件。
- 只修复该 repair item，改动范围保持最小。
- 遵循现有项目约定。
- 避免回滚用户改动或其他 worker 的改动。
- 不直接修改 `manager/plan.yaml` 或 OpenSpec archive 状态。
- 返回修改文件、验证命令和结果、总结以及 blocker。

Worker 禁止：

- 领取其他 repair item。
- 修改 repair 状态字段。
- 执行 `git add`、`git commit` 或 `git push`。
- 自动确认用户验证或归档 repair item。

## 队列校验

运行只读校验：

```bash
pnpm repairs:validate
```

查看队列状态：

```bash
pnpm repairs:status
```

校验会检查文件名、YAML 必填字段、`status`/`regression_test` 枚举、`id` 与文件名一致、`processing` 领取字段、`fixed` 工程验证证据、`verified` 用户验证证据和 `blocked` blocker。校验失败时先修正 repair 文件，不要继续自动执行。

校验可接收指定文件：

```bash
pnpm repairs:validate -- repairs/queue/repair-YYYYMMDD-001.md repairs/queue/repair-YYYYMMDD-002.md
python3 scripts/repairs/validate_repairs.py repairs/queue/repair-YYYYMMDD-001.md repairs/queue/repair-YYYYMMDD-002.md
```
