# Docs

`docs/` 保存长期有效的工程规范、AI 协作规则、模板使用说明和业务文档入口约定。

## 分类

| 目录                          | 作用                                                                  | 不放什么                                 |
| ----------------------------- | --------------------------------------------------------------------- | ---------------------------------------- |
| `docs/ai/`                    | AI 前端端到端交付规范和 Manager/OpenSpec 流程                         | 具体业务需求、接口契约、源码实现         |
| `docs/frontend/`              | 前端工程规范、组件维护说明和模板落地指南入口                          | 业务 PRD、接口契约、当前执行状态         |
| `docs/frontend/architecture/` | 技术基线、架构边界、目录分层、依赖方向                                | 临时实现计划、业务 PRD                   |
| `docs/frontend/standards/`    | 编码、组件、文件、样式、UI 状态和可访问性规范                         | 具体组件现状清单                         |
| `docs/frontend/components/`   | UI 组件治理指南、已落地组件统计清单、职责边界、复用判断和替代关系     | 未落地设想、一次性设计稿、临时实现计划   |
| `docs/frontend/guides/`       | 基于模板创建/迁入项目，以及使用或移除默认基座能力的操作指南           | 长期架构规则、当前执行状态               |
| `docs/api/`                   | 使用方项目的接口契约、OpenAPI 快照、mock、错误码和联调说明入口        | 前端组件规范、业务需求全文               |
| `docs/prd/`                   | 使用方项目的需求来源、PRD、用户路径、业务规则、验收标准和设计输入入口 | 代码实现细节、接口契约正文、当前执行状态 |
| `manager/`                    | Manager 当前计划、OpenSpec 批次编排和轻量 archive                     | 通用前端规范、真实业务长期归档           |
| `repairs/`                    | 小范围修复队列、repair runner 执行 list、用户验证和 repair archive    | Manager/OpenSpec 需求批次、长期业务归档  |
| `scripts/ralph/`              | Manager/OpenSpec 外部 shell runner 和运行状态输出                     | 需要提交的 transcript、失败日志          |

## Shared Component Usage

- 写 UI 前先查项目是否已有可复用组件、样式 token、hook 或工具函数，优先复用现有实现。
- `button`、`input`、`select`、`dialog`、`popover`、`tooltip`、`menu`、`card`、`empty state`、`loading` 等基础 UI，不要在业务代码里重复手写一套。
- 现有公共组件只缺少小能力时，优先在不破坏已有调用的前提下扩展它；不要为同一类 UI 新建平行组件。
- 只有当前页面或当前业务场景使用的组件，先放在所属模块内部；不要因为未来可能复用提前放入 `shared/ui`。
- 项目尚未提供公共组件时，先说明取舍，再在合适层级补最小基础封装。

## 读取顺序

- 处理前端任务时，先看 `docs/frontend/README.md` 判断前端文档入口。
- 处理前端实现任务时，先看 `docs/frontend/standards/README.md`，再看 `docs/frontend/standards/frontend-development.md`。
- 涉及组件命名、拆分、复用/新增判断或组件清单维护时，先看 `docs/frontend/components/components.md`、`docs/frontend/components/component-splitting.md` 和 `docs/frontend/components/component-inventory.md`。
- 涉及组件 props、可控/非可控、状态表达、数据边界或 shared primitive API 时，再看 `docs/frontend/standards/component-definition.md`。
- 涉及目录放置、页面私有组件、feature/entity/shared 划分或 hook 放置时，再看 `docs/frontend/standards/file-organization.md`。
- 涉及 loading、empty、error、disabled、focus、键盘操作或可访问性时，再看 `docs/frontend/standards/accessibility-and-ui-states.md`。
- 涉及技术选型、依赖方向、`src/` 分层或架构边界时，再看 `docs/frontend/architecture/technology-options.md`。
- 涉及新项目创建或已有项目迁入模板规范时，看 `docs/frontend/guides/project-bootstrap.md`。
- 涉及换肤（light/dark）、多语言或如何新增 token/语言、如何 opt-out 时，看 `docs/frontend/guides/theming-and-i18n.md`。
- 涉及环境变量、`shared/config`、Vite proxy 或 vendor 拆包时，看 `docs/frontend/guides/runtime-config-and-vite.md`。
- 涉及 Agent 协作方式、验证范围或交付要求时，看根目录 `AGENTS.md`；涉及前端实现细则时按本节入口读取 `docs/frontend/`。
- 涉及从产品、UX、视觉和 API 输入衔接到 Manager/OpenSpec、垂直切片、阶段 Gate 或完整前端交付路径时，看 `docs/ai/ai-frontend-delivery-best-practice.md`。
- 涉及 PRD 到 OpenSpec 批次规划、执行当前 Manager 批次、Goal 连续推进或 Ralph shell runner 时，看 `manager/plan.yaml`、`docs/ai/openspec-manager-flow.md` 和对应 `.agents/skills/manager-*`。
- 涉及一个需求该拆成几个 OpenSpec change、data-flow 是否单独建 change 时，看 `docs/ai/openspec-manager-flow.md#OpenSpec 拆分粒度`（权威规则在 `$manager-plan-from-doc` skill）。
- 涉及派发 subagent 执行 batch/wave、handoff 格式、并行判断或回写 `manager/plan.yaml` 时，由 `$manager-execute-current-batch` skill 自身定义，不读项目 doc。
- 涉及自然语言问题登记、小范围修复队列、用户验证后归档或 repair goal 循环时，看 `repairs/README.md`、`repairs/list.yaml`、`$repair-intake` 和 `$repair-runner`。
- 涉及接口契约、mock、错误码或联调说明时，在使用方项目中看 `docs/api/README.md`。
- 涉及 PRD、用户路径、业务规则或验收标准时，在使用方项目中看 `docs/prd/README.md`。

## 维护规则

- 长期稳定规则写入 `docs/frontend/` 或 `docs/ai/`。
- Manager 当前执行状态写入 `manager/plan.yaml`；完成后的轻量历史写入 `manager/archive/`。
- 模板只预留 `docs/api/` 和 `docs/prd/` 的入口说明；具体业务内容写入使用方项目自己的业务文档文件。
- 临时执行计划写入`docs/prd/template`模板文档。
- 文档示例应保持业务中性，优先使用 `ComponentName`、`feature-name`、`Entity`、`Resource` 等占位名。
- 当目录、命名或验证规则发生变化时，同步更新 `README.md` 文档地图。
