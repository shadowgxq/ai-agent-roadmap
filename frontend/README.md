# AI Agent Roadmap Frontend

这是 `ai-agent-roadmap` 的主前端项目，基于 `frontend-agent-template` 接入，用于承载面向用户的 Web 应用。

本项目与仓库中的 `agent-mini/` 相互隔离：`frontend/` 负责主前端，`agent-mini/` 负责 Python mini agent 与评测任务。两者拥有独立的依赖、运行命令和源码边界。

模板默认提供 `Vite + React + TypeScript + pnpm` 的最小可运行工程，并预装公司默认场景的基础前端依赖，同时保留 Agent 协作规则、文档结构、Manager/OpenSpec 工作流入口和源码目录骨架。

## 适用场景

- 新建一个 AI Agent 友好的前端项目。
- 将统一的协作规则、工程规范和文档结构迁入已有前端项目。
- 让 Agent 能通过稳定的入口文档、计划状态和规格流程推进需求。

## 项目内容

| 路径                                          | 作用                                                             |
| --------------------------------------------- | ---------------------------------------------------------------- |
| `AGENTS.md`                                   | Agent 协作入口规则。                                             |
| `docs/`                                       | 长期文档入口，包含 AI 协作、前端规范、API 和 PRD 目录说明。      |
| `manager/`                                    | Manager 计划、执行状态、archive。                                |
| `repairs/`                                    | 小范围修复队列（`$repair-intake` 登记、`$repair-runner` 执行）。 |
| `openspec/`                                   | OpenSpec 规格驱动工作流骨架。                                    |
| `.agents/skills/`                             | 项目级 Agent skills。                                            |
| `scripts/`                                    | Manager 校验和 Ralph shell runner。                              |
| `src/`                                        | 模板自身的最小可运行源码。                                       |
| `package.json`、`vite.config.ts`、`tsconfig*` | 默认前端工程配置。                                               |

## 快速开始

```bash
pnpm install
pnpm dev
```

常用验证命令：

```bash
pnpm check
pnpm typecheck
pnpm test
pnpm lint
pnpm build
```

## 文档入口

- `docs/README.md`：文档目录职责、读取顺序和维护规则。
- `AGENTS.md`：Agent 协作硬规则、验证范围和交付要求。
- `docs/ai/openspec-manager-flow.md`：Manager/OpenSpec 生命周期和批次推进规则。
- `docs/frontend/standards/frontend-development.md`：前端日常开发规范。
- `docs/frontend/guides/project-bootstrap.md`：基于模板创建新项目和已有项目迁入清单。
- `docs/frontend/guides/runtime-config-and-vite.md`：typed runtime config、开发代理和拆包规则。

## 工作流入口

Manager 用于把需求拆成可执行批次，并通过 OpenSpec 管理规格变更：

- 计划状态保存在 `manager/plan.yaml`。
- 执行规则参考 `docs/ai/openspec-manager-flow.md`。
- 连续推进优先使用 Goal 循环调用 `$manager-execute-current-batch`。
- 需要外部非交互 shell runner 时，使用 `scripts/ralph/ralph.sh`。
- repair 队列位于 `repairs/`，用 `$repair-intake` 登记、`$repair-runner` 执行。

## 业务边界

本仓库只保存通用前端工程模板，不保存具体业务域规则、业务实体、接口契约、页面需求或验收标准。

迁入具体项目后，业务内容应放入使用方项目自己的 `docs/prd/`、`docs/api/`、`openspec/specs/` 或对应业务文档目录。

## 默认技术基线

- `Node >=20.19`
- `pnpm`
- `React 18`
- `Vite 6`
- `TypeScript 5`

## 默认工程选型

以下能力会随模板预装并默认启用。使用方项目可以显式替换或移除，但应把它作为项目基线变更，同步源码、依赖、测试和文档：

- Routing：`react-router-dom`
- HTTP request：`axios`
- Server state：`@tanstack/react-query`
- Client UI state：`zustand`
- UI primitive：少量 Radix UI 基础包
- Icons：`lucide-react`，并在 `shared/icons` 预留业务自定义图标出口
- className：`clsx`
- Animation：`gsap`（按需引入，并尊重 `prefers-reduced-motion`）
- i18n：`i18next` + `react-i18next`（`shared/i18n`，默认提供 en/zh）
- Theming：CSS 变量 + `data-theme` 换肤（`shared/theme`，light/dark，零新依赖）
- Testing：`vitest`、React Testing Library、`jsdom`

表单、表格、schema validation、日期工具和图表库不默认预装，使用方项目按业务复杂度和团队约定补充。
