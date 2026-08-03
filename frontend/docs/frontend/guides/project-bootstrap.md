# Project Bootstrap

## 文档定位

本文档说明如何基于本模板创建新的前端项目，并补充已有项目迁入模板规范时的注意事项。

## 新项目默认流程

1. 从 Git 获取模板仓库，创建新项目目录。
2. 更新项目名称、仓库地址、README 项目说明和必要的 package metadata。
3. 安装依赖，并确认 `pnpm check`、`pnpm build` 等脚本是否适合当前项目。
4. 按项目约束补充根目录 `AGENTS.md`，明确沟通语言、验证命令、禁止操作、dirty worktree 和 git 操作规则。
5. 根据项目实际需要扩展 `src/app` providers、router、全局样式和 shared UI。
6. 确认 `docs/README.md`、`docs/frontend/README.md` 和前端规范仍适合项目当前技术栈。
7. 在使用方项目中补充业务 PRD、API contract、用户路径和验收标准。
8. 如果使用 OpenSpec，补充项目专属 specs，并确认 Manager/OpenSpec 流程是否启用。
9. 清理模板占位说明、示例内容和项目不需要的默认依赖。
10. 完成下方“初始化后检查”，确认通用模板内容和业务内容已经分离。

`src/` 同时是可运行源码和迁移参考，使用方按实际边界选择性复用。

## 默认依赖处理

模板 `package.json` 默认预装 `react-router-dom`、`axios`、`@tanstack/react-query`、`zustand`、Radix UI 基础包、`lucide-react`、`clsx`、`gsap`、`i18next`、`react-i18next`、`vitest` 和 React Testing Library，并默认接入 theme 与 i18n。它们是公司默认初始化选型，不是使用方项目不可替换的强制技术约束。

新项目可以直接保留默认依赖作为初始基线。已有明确团队选型时：

- 已有等价方案可以保留，不需要为了模板替换。
- 不使用的默认依赖可以在初始化后删除。
- 替换 routing、request、state 或 UI primitive 时，应同步更新 `src/app`、`src/shared` 和 `docs/frontend/architecture/technology-options.md`。
- 移除 theme 或 i18n 时，应按 `theming-and-i18n.md` 完成调用方、测试、模板骨架、依赖和规则文档的同步清理。

## 初始化后检查

- `src` 是否具备 `app`、`pages`、`widgets`、`features`、`entities`、`shared`。
- `shared` 是否具备 `api`、`config`、`hooks`、`icons`、`styles`、`testing`、`ui`、`utils`。
- `AGENTS.md` 是否说明禁止项和验证要求。
- `docs/README.md` 是否能解释项目文档结构。
- 是否记录并处理了迁入差异、`.incoming` 文件和人工后续事项。
- 是否保留了 Vite + React + TypeScript 的基础启动和构建文件。
- 业务规则是否已经从通用模板中分离。
- 项目是否有明确的验证命令。
- `.env.example`、`src/shared/config/` 与部署环境变量是否一致，客户端配置中是否排除了密钥。

## 已有项目迁入

已有前端项目需要引入模板规范时，迁入是次级路径，不是新项目默认方式。

1. 先确认目标项目已经存在的工程配置、源码分层、文档目录和 agent 协作规则。
2. 只迁入目标项目缺少且适用的模板内容，不覆盖目标项目已有文件。
3. 如需迁入源码骨架，可以参考 `src/`，但应按目标项目已有目录和命名约定落地，不直接覆盖目标项目源码。
4. 如需迁入 `docs/`、`openspec/` 或 `manager/`，先保留目标项目已有业务文档和计划状态。
5. 迁入冲突应记录为 `.incoming` 或迁入报告，由人工确认后再合并。
6. 迁入后同步更新文档地图，说明哪些规则来自模板，哪些是项目专属规则。

## 使用方项目需要补充的内容

- 项目专属技术栈和依赖版本。
- 路由、认证、权限、主题、国际化等项目级方案。
- API contract 和错误处理规则。
- 业务 PRD、用户路径和验收标准。
- 组件库现状和 shared UI API。

## AGENTS.md 迁入清单

基于模板创建新项目或迁入已有项目时，建议在 `AGENTS.md` 补充以下项目专属信息：

- 项目名称和产品定位。
- 默认沟通语言和输出格式。
- 是否允许 agent 自动安装依赖、启动 dev server、执行 build。
- 推荐验证命令，例如 typecheck、lint、test、format check。
- 业务文档入口，例如 PRD、API contract、OpenSpec specs。
- 关键目录边界，例如业务模块、shared UI、request client、route config。
- 只读或禁止修改的目录。
- dirty worktree 和 git 操作约束。
- 部署、环境变量和敏感配置处理规则。

## 新项目首轮落地任务

建议按以下顺序执行：

1. 建立 `src` 分层目录。
2. 建立 `docs` 文档地图。
3. 补充项目技术栈和脚本说明。
4. 建立 shared UI 的最小入口规则。
5. 建立 request、routing、state 的职责边界。
6. 建立验证命令和质量门禁。
7. 补充业务 PRD 和 API contract。
8. 完成“初始化后检查”。
