# OpenSpec Manager 多角色自动化工作流

> Manager 家族六件套 + 项目级多角色编排的单一说明文档。总览索引见 [SKILLS-OVERVIEW.md](SKILLS-OVERVIEW.md)。

## 是什么

把「需求 → OpenSpec → 批次 → 执行 → 回写 → 归档」用最少状态跑通，并按互联网研发流程叠加多角色协作：**产品提需求 →（可选）需求评审会 → 生成方案 →（可选）方案评审 → 开发 → 测试 → 门内自动修复 →（必要时）手动 bugfix**。Manager 起管理/编排作用，具体工作派给角色化 subagent。**两处多角色评审都是可选项、默认关闭**：需求评审会靠显式调用开启，方案评审门禁靠运行参数 `review=on` 开启；默认主链路只保留 validate + apply 后 verify 两道硬门禁和 change→apply 人工边界。

**组成（六件套，共享唯一状态源 `manager/plan.yaml`）**：

| Skill                           | 环节                           | 触发                   | 一句话                                                                                                                                      |
| ------------------------------- | ------------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `manager-prd-review`            | 需求评审会（可选）             | 手动（显式调用即开启） | PRD 进排期前的多角色并行评审，用户对 BLOCKER 拍板，回写评审 marker；默认流程跳过                                                            |
| `manager-plan-from-doc`         | 排期                           | 手动                   | 把 PRD 规划成 `plan.yaml` 的 requirements、`openspec[].inputs`、batches 和 waves                                                            |
| `manager-execute-current-batch` | 生成 + 开发 + 验收（评审可选） | 手动 / Goal 循环       | 跑 change/apply 批次；apply 后 verify 必跑，可修复失败在门内最多自动修复 2 次，终态失败才 block，从不归档                                   |
| `manager-run`                   | 连续推进驱动                   | 设为 Goal / 手动       | Goal 一句话驱动：每轮跑一个 `next` selection、内建上下文纪律、轮末 `MANAGER-RUN:` footer 判停；`review=on` 透传给 execute；循环由 Goal 提供 |
| `manager-bugfix`                | 人工发起的修复回路             | 手动                   | 处理用户新报问题或继续修复 terminal blocked entry，按归档状态分流并产出 `findings/`                                                         |
| `manager-archive-completed`     | 归档                           | 手动（显式）           | Stage A OpenSpec archive → `done`；Stage B 剪枝出 plan                                                                                      |

## 三层切分原则

多角色能力严格分三层：

- **机制归全局 skill**（`~/.agents/skills/`）：通用规则——状态机、门禁、路由解析逻辑、handoff 格式。上游模板同步为纯增量。
- **映射归项目**（`manager/roles.yaml`）：哪类工作派给哪个 `agent_type`。删除此文件即整体回退旧的单 subagent 行为。
- **人设归 agent 文件**（项目 `.claude/agents/*.md`）：角色职责、工具权限（运行时强制）、硬约束、上下文隔离。

> 绝不修改 `.claude/skills/openspec-*`（OpenSpec CLI generatedBy 生成物，升级会覆盖）。`openspec/config.yaml` 的 `rules` 键只能是 schema artifact id（proposal/specs/design/tasks），无法注册新 artifact。

### UI Skill 提示注入

UI Skill 不增加新的 Manager/OpenSpec 阶段，也不写入 `plan.yaml` 状态。项目通过 `openspec/config.yaml` 把调用要求注入 artifact：初始化或重做产品级视觉体系时，`design` 提示显式使用 `$ui-ux-pro-max` 与 `$design-system`；每个 `[ui]` task 的描述显式写入 `Use $frontend-design`，apply agent 读取任务后执行。普通 `[logic]` task 不调用 `frontend-design`。

## 状态模型

`manager/plan.yaml` 是唯一真相源，`phase`/`state`/`review`/`current` 只由 `plan_tool.py` 写。

- **phase**（OpenSpec 生命周期到哪步）：`change` → `apply` → `archive` → `done`
- **state**（当前 phase 能否执行/到哪）：`planned` / `ready` / `in-progress` / `blocked` / `cancelled`；apply 门内自动修复期间保持 `in-progress`，`blocked` 只表示自动化无法安全继续的终态
- **review**（change 制品评审门禁，change 完成后出现、`done` 时移除）：`pending`（自动写入，apply 被 hold）/ `approved`（apply 可执行；默认 review=off 由 execute 当轮直接放行写入，review=on 时由评审通过写入）
- **批次阶段**：不存储（`behavior` 已废弃，读到只 warn），由批次引用条目的最小 phase 派生

`openspec[].inputs` 是可选的通用 change 级只读输入引用，不是状态；没有显式 supporting input 时不生成，旧 plan 行为不变。每项记录 `id`、开放式 `kind`、文件/目录路径或 URI `source`、`required` 和可选 `scope`，不限定 UX、Contract、Schema、数据、设计资产等具体领域。每个明确交给下游 OpenSpec/实现/验证消费的 source 独立成 input，父文档不能代替它声明的子资源；来源证据、参考资料和工程规范链接本身不构成 handoff，主 PRD 也不因子文档回链而重复进入 inputs。`scope` 是 execute 的 source 内读取边界，新计划使用开放式 `<locator-kind>:<value>`；有完整稳定 locator 时按 change-specific + shared/global 范围收窄，否则省略并读取整个 source。plan 不保存正文或运行时可用性，execute 解析后只在 handoff 增加 `status`/`notes`；必需输入在首次 start 前不可读时不启动该 entry，unfinished Auto-Repair 恢复时原必需输入失效则记为 terminal prerequisite 并 block，避免遗留 stale `in-progress`。

**权威划分**：plan 只写初始态（`phase: change`/`state: planned`）；execute 只推进 change 和 apply（change 完成自动写 `review: pending`）；archive-completed 承担全部归档（`archive`→`done`→剪枝）。

## 五环节全景流转

```
docs/prd/features/NN-*.md（产品提需求）
  │
  ①（可选，默认跳过）manager-prd-review ── 多角色并行评审（roles.yaml prd_review 路由，全 review-only）
  │     显式调用才执行；用户对 BLOCKER 逐条拍板 → product-manager 修订 PRD → 回写「需求评审：通过」marker
  │     跳过时人工 intent 闸落在批次执行确认 + change→apply 边界
  │
  ② manager-plan-from-doc ── 规划 requirements + openspec[].inputs + batches（preview 显示输入映射与需求评审状态）
  │
  ③ manager-execute-current-batch（change 段）
  │     opsx:ff 生成四件套（proposal/design/specs/tasks）→ openspec validate
  │     → 方案评审门禁（可选参数 review，默认 off）
  │         review=off（默认）→ 不派评审角色，当轮直接 set-review approved（报告标注「直接放行」）
  │         review=on → 派 roles.yaml review 路由（gate: auto 为 AI 自愈闸）：
  │             无 BLOCKER → 自动 set-review approved
  │             有 BLOCKER → 按 backwrite 归属回派修订 + 复审（限 2 轮）
  │             需产品决策/硬冲突/轮次耗尽 → 升级待决，保持 pending
  │     ★change→apply 边界：停下汇报（放行/自动通过/升级待决），等用户确认——review=off 时这是实现前唯一人工看方案的点★
  │
  ③ manager-execute-current-batch（apply 段）
  │     按 tasks.md 分节派发实现代码；[ui] task 按任务 Prompt 加载 frontend-design
  │     → apply 后 verify AI 门禁（必跑；roles.yaml verify 路由：qa + 含前端则 ui-ux-reviewer）
  │         无 CRITICAL → advance 到 archive
  │         有 CRITICAL / checks 或 strict validate 失败
  │           → entry 保持 in-progress，门内 Auto-Repair（最多 2 次；每次完整复验）
  │               修复通过 → advance 到 archive
  │               不可安全修复 / 无进展 / 2 次耗尽 → block
  │
  ④ manager-bugfix（用户显式要求走修复流程处理新问题，或要求继续处理 terminal blocked 时）
  │     分流 → Repair Loop 回派修复 → 复验 → 必要时 start+advance 解锁 → 产出 findings/
  │
  ⑤ manager-archive-completed（显式请求）
        Stage A opsx:archive → done ；Stage B 剪枝到 manager/archive/
```

## 多角色路由（`manager/roles.yaml`）

execute skill 派发前按 `routes` 解析 `agent_type`；未命中回退 `default`（通用 subagent）。

| route        | 用途             | 关键机制                                                                                                                  |
| ------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `change`     | 生成四件套       | 用 `default`（opsx:ff 含 tasks.md 技术拆解，product-manager 被禁写故不派它）                                              |
| `prd_review` | 需求评审会阵容   | 仅显式调用 `manager-prd-review` 时使用；`agents` 列表并行，全 review-only                                                 |
| `review`     | 方案评审门禁阵容 | 仅运行参数 `review=on` 时派发（默认 off 直接放行不派）；`gate: auto` 决定 AI 自愈闸 vs 人工评审；`when` 条件按 tasks 分节 |
| `apply`      | 开发派发         | `split_by_tasks_section: true` 按 `## 后端`/`## 前端` 拆派；`order` 后端先行；`shared_write_points` 跨 change 串行        |
| `verify`     | 验收门禁（必跑） | `qa` 必派；`when: has_frontend_section` 时并行加 `ui-ux-reviewer` UI 走查                                                 |

**路由要点**：

- `agents` 列表并行派发；`when`（如 `has_frontend_section` / `has_backend_section`）按目标 change 的 tasks.md 分节决定是否派该角色。
- `split_by_tasks_section: true`：apply 把一个 change 拆成每个 tasks.md 顶级分节一个派发，handoff 只允许该分节任务；按 `order` 派（后端先落契约与 `types.ts`），分节任务互不相干时才并行。
- 本前端模板通过 OpenSpec rules 在前端 checkbox task 上标记 `[ui]` / `[logic]`；标签不改变 `roles.yaml` 的分节路由，只负责把对应 Skill 调用要求带入任务 Prompt。
- `shared_write_points`（如 `frontend/src/services/types.ts`）：涉及该文件的后端分节即使在 parallel wave 也跨 change 串行，其余分节照常并行——防契约文件并行写冲突。
- 路由从不放松任何门禁，只决定「谁执行」。

### 示例：`manager/roles.yaml`

下面是一份完整的项目路由表，别的项目按自己的角色/端划分自定义；无此文件则全部回退 `default`。

```yaml
# 角色路由表 —— manager-execute-current-batch 派发 subagent 时按此选择 agent_type。
# 角色定义（人设 / 工具权限）见 .claude/agents/*.md；本文件只声明"哪类工作派给哪个角色"。
# 没有命中路由的派发一律回退 default（通用 subagent），删除本文件即整体回退旧行为。
routes:
  # change：opsx:ff 一次性生成四件套（含 tasks.md 技术拆解），
  # product-manager 被禁写 tasks 技术拆解，故保持通用 subagent 生成。
  change:
    agent_type: default

  # 需求评审会（可选环节，显式调用 manager-prd-review 时使用）：全员 review-only，只出意见不改文件。
  prd_review:
    agents:
      - agent_type: product-manager # 需求完整性：验收可测、边界显式、不冲突不越界
      - agent_type: ui-ux-reviewer # 交互合理性：流程图/原型一致、路径成立、状态齐全
      - agent_type: frontend-dev # 前端可行性：技术风险、实现成本、依赖影响
      - agent_type: backend-dev # 后端可行性：数据模型、接口契约、性能与降级
      - agent_type: qa # 可测性：验收标准可验证、场景可构造

  # 方案评审门禁阵容：仅运行参数 review=on 时派发（默认 off：change 完成直接 set-review approved 放行，不派评审）。
  # gate: auto —— review=on 时的 AI 自愈闸（与 verify 门禁对称）：无 BLOCKER 自动 set-review approved；
  #   有 BLOCKER 按 backwrite-matrix 回派修订该 artifact + 复审（限轮次，保持 pending）；
  #   需产品决策 / 硬冲突 / 轮次耗尽 → 升级给用户。删 gate: auto 一行即回退人工评审（意见仅供参考，用户 set-review 放行）。
  review:
    gate: auto
    agents:
      - agent_type: product-manager # PRD 覆盖 / 验收标准 / openspec config rules 遵守
      - agent_type: ui-ux-reviewer # 交互合理性：流程图/原型一致、步数、状态与异常路径
      - agent_type: backend-dev # design/tasks 后端分节技术可行性（仅意见）
        when: has_backend_section
      - agent_type: frontend-dev # design/tasks 前端分节技术可行性（仅意见）
        when: has_frontend_section
      - agent_type: qa # 可测性：spec scenario 是否可验证

  # apply：按 tasks.md 分节拆派（config 已强制 ## 后端 / ## 前端），handoff 只允许该分节任务。
  apply:
    split_by_tasks_section: true
    # 跨 change 共享写点：涉及契约变更的后端分节即使在 parallel wave 也须跨 change 串行。
    shared_write_points:
      - frontend/src/services/types.ts
    sections:
      - match: '后端|backend'
        agent_type: backend-dev
      - match: '前端|frontend'
        agent_type: frontend-dev
    order: # 后端先行（契约与 types.ts 先落地），前端随后
      - backend-dev
      - frontend-dev
    fallback: default

  # apply 后 verify 门禁：qa 必派（无 Write/Edit）；含前端分节的 change 并行加 ui-ux-reviewer UI 走查。
  verify:
    agents:
      - agent_type: qa
      - agent_type: ui-ux-reviewer
        when: has_frontend_section
```

> 五个角色人设/工具权限见项目 `.claude/agents/`：`product-manager`、`ui-ux-reviewer`（只读）、`frontend-dev`、`backend-dev`、`qa`（只读）。`qa` 与 `ui-ux-reviewer` 无 Write/Edit，天然只能出意见。

## 质量门（两可选 + 一必选）+ 人工闸口

两处多角色评审门都是**可选项、默认关闭**；默认主链路的质量保障 = `openspec validate` + change→apply 人工边界 + apply 后 verify 门禁。要更重的流程再按需打开评审门：

| 门                                      | 默认           | 开启方式                                  | 谁判                          | 通过                                    | 不通过                                             |
| --------------------------------------- | -------------- | ----------------------------------------- | ----------------------------- | --------------------------------------- | -------------------------------------------------- |
| **需求评审会**（prd-review，change 前） | 关（跳过）     | 显式调用 `manager-prd-review`             | 人（AI 出意见）               | 用户拍板通过 → 写 marker                | product-manager 修订 PRD → 复审                    |
| **方案评审**（review 门禁，apply 前）   | 关（直接放行） | 运行参数 `review=on`（Goal 行或调用时传） | AI 自愈（`gate: auto`）或人工 | 无 BLOCKER → 自动 `set-review approved` | 回派修订 + 复审（限 2 轮）/ 升级待决               |
| **验收**（verify，apply 后）            | **开（必跑）** | 不可关                                    | AI 门禁                       | 无 CRITICAL → advance                   | 门内 Auto-Repair 最多 2 次；不可修复或耗尽才 block |

**人工闸口**：① 批次执行确认 + change→apply 边界汇报（默认 review=off 时这是实现前唯一人工看方案的点，也处理升级待决项）；② 归档（显式请求，git/deploy/publish 永不自动）；③ 打开需求评审会时追加「BLOCKER 拍板」闸。

**何时开评审门**：需求含糊/跨端影响大/返工代价高的批次建议 `review=on`（乃至先开 prd-review 评审会）；小步快跑、需求清晰、demo/POC 类工作直接默认跑。

### 方案评审门禁（运行参数 `review`，默认 `off`）

- **`review=off`（默认）**：change 完成 → `advance` 照常写 `review: pending` → execute **当轮直接 `set-review approved`**（报告标注「直接放行（多角色评审未开启）」），不派任何评审角色。状态机不变，只是放行方拿掉了评审环节。直接放行只针对本轮完成的 change：历史遗留 / 上次 `review=on` 升级待决的 pending 条目绝不被 off 模式代批，保持 hold 并在报告中列出。
- **`review=on`**：派 `roles.yaml` `review` 路由角色（review-only），意见收进 `review-notes.md`；verdict 消费方式看路由的 `gate` 声明（下节）。无 review 路由时回退派单个 `default` subagent 出意见 + 人工放行。

### 方案评审 AI 自愈闸（`review=on` 且 `review.gate: auto`）

与 apply 后 verify 门禁对称。change 完成变 `review: pending` 后：

1. 派 `review` 路由角色（review-only，不写文件），意见收进 `review-notes.md`；
2. **无 BLOCKER/CRITICAL** → skill 代写 `set-review approved`，apply 可执行；
3. **有 BLOCKER** → 按 backwrite 归属回派修订该 artifact（proposal/specs→product-manager，design/tasks→对应端）→ 重跑 `openspec validate` → 复审，限 2 轮，全程保持 pending；
4. **需产品决策 / 意见硬冲突 / 轮次耗尽** → 升级：保持 pending，报告列「升级待决」，不自动通过。

AI 闸只写 `approved`、从不写 `blocked`（终态 blocked 由 apply Auto-Repair Gate 判定）、从不自行跨进 apply。人工不做逐条 set-review，只处理升级待决 + change→apply 边界确认。**删 roles.yaml 里 `gate: auto` 一行即回退成人工评审**（意见仅供参考，只有用户 `set-review approved` 放行）。

### change→apply 边界 checkpoint

默认 `review=off` 直接放行、`review=on` 的 AI 闸自动 approve，`review: pending` 的天然停点都不存在，故 auto scope 把停点重锚到「change 阶段全部做完（+ 已开启的评审跑完）」：**停下汇报（放行/自动通过/升级待决），即便预授权也停**，等用户确认再进 apply；除非 Goal 显式授权穿越边界。`review=off` 时这个边界是实现前唯一人工过目方案的机会，汇报不得省略；升级待决条目在用户处理前永不进 apply。

### apply Auto-Repair + 手动 bugfix

apply 的 checks、`openspec validate --strict` 或 verify 失败，先由 `manager-execute-current-batch` 在当前 selection 内处理：初次失败标记为 `Attempt 0 (Initial)`，entry 保持 `in-progress`，最多进行 2 次聚焦修复；每次修复后重跑相关 checks、strict validate 和完整 verify route。同一次 gate 使用稳定 `gate_run_id` 追加 `verify-report.md`，会话中断后从下一未用次数继续，不重置预算；若 verdict 已写而 plan transition 未写，下一轮只补一次对应的 `advance`/`block`，不重新派发。明确属于当前实现、相邻测试或 task 落实偏差的问题可自动修复；涉及产品决策、PRD/已批准 artifact 冲突、外部授权、不可复现、越出当前 change，或者连续无进展时直接判终态失败。只有终态失败才写 `blocked`，自动修复过程不调用 `manager-bugfix`、不生成 `findings/`。

用户显式要求走 bugfix/repair 流程处理执行后发现的新 bug，或要求继续处理 terminal blocked entry 时才走 `manager-bugfix`，分流三句话：

1. **绑定未归档 change**（含 Auto-Repair 不可处理或耗尽后的 terminal blocked entry）→ Repair Loop 修原 change；
2. **已归档/不绑定** → 行为变更新建 `fix-<slug>` change；琐碎小修走项目 `repairs/` 队列；
3. **需求变更非缺陷** → 回 PRD 流程（改 `docs/prd/` → prd-review → plan-from-doc）。

Repair Loop：复现优先 → 根因分类（取最上游）→ 回派修复（代码错→对应端；artifact 错按 backwrite-matrix 归属）→ 复验（qa 聚焦偏差 + 不放松门禁）→ 状态回写（`start` 解锁 + `advance`，限 2 轮）→ 闭环产出 `findings/<date>-<slug>.md`。findings 是 post-apply 证据层，不进 DAG、不改 config，随 change 目录归档。根因上溯到 PRD 本身时须经 product-manager + 用户拍板，并在 finding 回写矩阵追加 `docs/prd/<文件> §N` 行。

## 证据文件（单一写入方 = 主会话/skill 执行者）

评审与验收角色可能只读，证据一律由 skill 执行者落盘，评审角色只读：

| 文件                                     | 产出                                                    | 消费                      |
| ---------------------------------------- | ------------------------------------------------------- | ------------------------- |
| `openspec/changes/<id>/review-notes.md`  | 方案评审每轮意见（追加日期小节；仅 `review=on` 时产出） | 人工抽查、回派修订依据    |
| `openspec/changes/<id>/verify-report.md` | 初验及每次 Auto-Repair 完整复验裁决（追加日期小节）     | 门内修复聚焦、bugfix 输入 |
| `openspec/changes/<id>/findings/*.md`    | bugfix 闭环记录（根因/回写矩阵/复验）                   | qa 回归防复发、随目录归档 |

## plan_tool.py 子命令（execute skill 捆绑，依赖 PyYAML）

```bash
python3 <execute-skill-dir>/scripts/plan_tool.py --plan manager/plan.yaml <subcommand>
```

| 子命令                                                            | 职责                                                                                                   |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `next --scope auto\|full\|change-only\|apply-only [--batch <id>]` | 选下一个可执行 batch/wave/entries（含 depends_on、blocked、review 门禁），报告被 hold 条目与待归档批次 |
| `start --change <id>...`                                          | 置 `in-progress`（无 guard，bugfix 用它救活 blocked entry）                                            |
| `advance --change <id>... --completed change\|apply\|archive`     | 按转移表推进并重指 current（change→apply+`review: pending`；apply→archive；archive→done）              |
| `block --change <id>... --reason <text>`                          | change 失败可直接阻塞；apply 仅记录自动修复不可用、无进展或耗尽后的终态阻塞                            |
| `set-review --change <id>... --review approved\|pending`          | 落评审结论（AI 闸或人工）                                                                              |
| `repoint-current` / `validate`                                    | 重算游标 / 深度校验结构、枚举、引用                                                                    |

> 无 `unblock` 子命令；bugfix 靠 `start` 无 guard 救活 blocked。若日后升级 plan_tool 加了状态校验，应正式补 `unblock`。

## 执行入口映射（项目侧 OpenSpec skill）

Manager skill 不内置 OpenSpec CLI 细节，入口标签与依赖 skill 由项目提供：

| 阶段        | 入口标签       | 依赖 skill                | 归属              | 动作                                                  |
| ----------- | -------------- | ------------------------- | ----------------- | ----------------------------------------------------- |
| `change`    | `opsx:ff`      | `openspec-ff-change`      | execute           | 生成四件套                                            |
| `apply`     | `opsx:apply`   | `openspec-apply-change`   | execute           | 执行 tasks 落代码                                     |
| verify 门禁 | `opsx:verify`  | `openspec-verify-change`  | execute           | 核对实现与制品一致性，CRITICAL 先进入门内 Auto-Repair |
| archive     | `opsx:archive` | `openspec-archive-change` | archive-completed | specs 同步 + 目录归档                                 |

## 执行范围 scope（默认 auto）

由驱动方（Goal 或用户）传入，**由 skill 强制**而非靠 prompt：

| scope          | 行为                                                                                                               | 停止条件                                     |
| -------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| `auto`（默认） | 两段式：先做完所有 change（`review=on` 时含方案评审门禁）→ change→apply 边界停下汇报 → 用户确认后跑 approved apply | 无可执行工作（剩余全部待归档/升级待决/阻塞） |
| `full`（显式） | batch 顺序深度优先：一批 change 完接着跑该批 apply                                                                 | 无 change/apply 工作                         |
| `change-only`  | 只跑 change，绝不进 apply                                                                                          | 全 plan 无 change 工作                       |
| `apply-only`   | 只跑 `review: approved` 的 apply，绝不跑 change                                                                    | 无可执行 apply                               |

显式 scope 的价值是**硬约束**（锁死本次循环只做某类事，用在新旧工作混杂时）；日常默认 `auto` 即可。

## Goal 连续跑（`manager-run`）

日常连续推进由 **`manager-run`** 驱动。设计目标：**Goal 行只需一句话，不再手写长 prompt**——预授权、上下文纪律、停止条件全部内建在 skill 里。**循环由 Goal（harness 层）提供**——每轮重新拉起 `manager-run` 跑一个 `next` selection，靠 turn 边界在轮次间 compaction；skill 每次跑完一轮就 return，绝不自己在一个 turn 内 loop。

把这一句设为 Goal 即连续推进：

```text
Run this project's $manager-run each round. Re-invoke only while the previous
round ended with `MANAGER-RUN: CONTINUE`; on any `MANAGER-RUN: STOP(...)` line,
stop and relay its report.
```

锁定阶段在 Goal 行追加 `scope=change-only` / `apply-only`（默认 `auto` 两段式）；要开方案评审门禁在 Goal 行追加 `review=on`（默认 off 直接放行，参数逐轮透传给 execute）。

**内建上下文纪律**（常开，不设档位，不放松任何门禁）：

- 只看 `current` + `next` 输出定本轮，不重读已完成条目的 evidence；
- dev 角色派发只回状态摘要（batch/wave、各 change 的 phase/state/review、阻塞一句话），不贴 diff/全文/长日志；
- **review/verify 角色的逐条裁决豁免限幅**（level + artifact/§ 引用 + 一句理由），保证 `review-notes.md` / `verify-report.md` 证据完整——只精简废话，不精简条目。

**停止协议（轮末 footer，Goal 只 key 这个标记判停）**：

| Footer                           | 含义                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `MANAGER-RUN: CONTINUE`          | 本轮有推进且还有可执行工作                                                                              |
| `MANAGER-RUN: STOP(boundary)`    | change→apply 边界：报告直接放行/自动通过项 + 升级待决；**用户重启同一 Goal 即确认进 apply**             |
| `MANAGER-RUN: STOP(no-work)`     | 无可执行工作（剩余全部待归档/升级待决/阻塞）                                                            |
| `MANAGER-RUN: STOP(blocked)`     | 出现 terminal blocked 条目（自动修复不可用、无进展或耗尽）→ 汇报原因；`manager-bugfix` 仅作显式人工后续 |
| `MANAGER-RUN: STOP(no-progress)` | cursor 没动且无 advance/block——软失败，绝不静默重跑                                                     |

> 边界由该协议强制而非 plan 状态：即便条目全部直接放行/自动通过 + 预授权，到边界也发 `STOP(boundary)`、绝不发 `CONTINUE`。停点终结 Goal 循环，**用户重新启动 Goal 本身就是放行 apply 的确认动作**。评审升级待决项留给用户；归档永远显式操作。详见全局 `manager-run` SKILL。

## 各 skill 细则

### manager-prd-review（需求评审会，可选环节）

- **触发**：手动（**默认流程跳过**，显式调用即开启），输入 `docs/prd/features/NN-*.md`；未指明时列尚未生成 artifacts 的候选 PRD。已生成四件套的 PRD 不走本 skill（时机已过，改用 `review=on` 的方案评审门禁消化）。跳过时人工 intent 闸落在批次执行确认 + change→apply 边界。
- **流程**：读 PRD 与本期范围 → 并行派 `prd_review` 路由角色（全 review-only，各返回 BLOCKER/SUGGESTION + PRD §N）→ 主会话合并纪要（冲突并列不裁决）→ 用户对 BLOCKER 逐条拍板 → product-manager 修订 PRD → 通过后 skill 写 marker `> 需求评审：通过 YYYY-MM-DD（manager-prd-review；BLOCKER N 条已拍板：采纳 a / 驳回 b / 延后 c）`。
- **边界**：只读项目文件 + 修订 `docs/prd/`（内容修订只经 product-manager、只在拍板后；marker 由本 skill 写）；不动 openspec/、plan.yaml、代码；不 git。

### manager-plan-from-doc（排期）

- **作用**：PRD → `plan.yaml` 的 requirements、可选通用 `openspec[].inputs`、batches 和 waves。先覆盖目标、功能、业务规则、用户路径、交互/状态和正式验收等全部规范性章节，再去重为可独立验证的行为子句；正式验收不是唯一来源。只规划，不建 artifact、不实现、不执行、不归档。本地 PRD 回写「Manager 规划覆盖」marker。
- **验收归属**：一个源条目同时描述上游操作和后续页面效果时继续拆成 surface 级子句；上游 change 只承诺自身可观察结果，预算/统计等联动分别归入引入该 surface 且声明真实 `depends_on` 的 change。复用 requirement 必须按“每条 acceptance × 每个 consumer”证明闭环，不能用“各自处理自己的部分”代替。
- **inputs**：只跟随用户或 downstream handoff/input section 明确声明给 OpenSpec/实现/验证消费的 source；provenance、evidence、bibliography、related docs 和冲突优先级引用不自动成为 input，主来源回链不重复映射。每个真实 source 逐项结算；无 inputs 时不补猜，不扫描、不复制正文。
- **preview 门禁**：显示全源覆盖计数、行为子句 ownership、跨 change 验收审计、复用 requirement 闭环、input discovery/accounting/mapping，以及每个 wave 的预计写入区域与 shared write points。任何 gap、未结算 input、未来 surface 承诺或缺少隔离证据的 parallel wave 都不能进入确认。
- **写入与并行**：只写初始态（不写 `behavior`/`review`）。`parallel: true` 需要代码感知的独立写入证据，否则串行；确认写入后按 preview 逐项 reconciliation，再跑 Manager 结构 validator。转移规则指向 execute 不复述。

### manager-execute-current-batch（生成 + 开发 + 验收，评审可选）

- **作用**：跑 change/apply 批次，用 `plan_tool.py` 选工作、展示预览等确认、派角色化 subagent 跑 OpenSpec、跑门禁、回写状态。**从不归档**。
- **门禁**：change 成功 = 验收 + checks + `openspec validate`，完成写 `review: pending` → 按运行参数 `review` 处理（默认 off 当轮直接放行；on 时走方案评审门禁）；apply 成功 = 验收 + checks + `openspec validate --strict` + verify subagent 无 CRITICAL（必跑）。apply 首次失败保持 `in-progress` 并进入最多 2 次的门内 Auto-Repair；修复通过后正常 advance，不可安全修复、无进展或预算耗尽才 block。
- **subagent handoff**：每个派发生成 handoff（含 `agent_type`、`tasks_section`、入口、required skill、结构化 inputs、推导 checks、并行标志）；execute 按 source 与可选 locator scope 解析，inputs 在 change/apply/review/verify 间持续传播；无 inputs 时传空列表且不补猜，subagent 不改 plan.yaml、不跑 archive。
- **并行**：仅 `next` 说 `parallel: true` 且输入独立、不撞 `shared_write_points` 时并行；否则串行。

### manager-bugfix（修复回路）

见上「apply Auto-Repair + 手动 bugfix」。**手动触发**（显式 `$manager-bugfix`、要求走修复流程处理执行后问题，或要求继续修复 terminal blocked entry 时），不参与 execute 门内自动修复，也不因提及 bug 自动触发。references 三件套：`root-cause-checklist.md` / `backwrite-matrix.md` / `finding-template.md`。

### manager-archive-completed（归档）

- **两段式**：Stage A 对 `phase: archive` 逐 change 跑 `opsx:archive` + `advance --completed archive` → `done`；Stage B 把 `done` 搬到 `manager/archive/` 并剪枝 plan（清空 wave/batch、无用 requirements）。
- **Manager archive ≠ OpenSpec archive**：Stage A 是 OpenSpec archive（specs 同步 + 目录移入 `openspec/changes/archive/`，必须经 `openspec-archive-change`，绝不手搓）；Stage B 只搬 plan 条目。
- 用户绕过本 skill 直接跑 archive 致 plan 漂移时，用 `advance --completed archive` 对账。写完跑 `validate`。

## 边界与约束（全家共用）

- 状态只经 `plan_tool.py` 写；subagent 从不直接改 `plan.yaml`。
- 不自动 `git add/commit/push`；archive/deploy/publish 一律需用户显式确认。
- 开发阶段不主动跑 dev server/build/deploy 等高副作用命令（一次性验证脚本除外）。
- 角色派发遵守各 agent 自身硬约束与写入范围；评审型派发 handoff 标注 review-only（只出意见、不改文件、不勾任务）。
