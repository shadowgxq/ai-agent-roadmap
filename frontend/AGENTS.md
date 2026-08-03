# AGENTS.md

本文件是前端项目 agent 协作入口规则。

## Communication

- 默认使用中文沟通和解释。
- 技术术语、命令、路径、文件名、环境变量、配置键、错误信息、日志和 URL 保持原文。

## Working Principles

- 优先理解用户目标、当前上下文、交互路径和数据流；不清楚时先查现有实现和文档。
- 如果仍有影响结果的歧义，先提出简短问题；影响较小时可以自主判断，并在交付时说明。
- 改动遵循最小范围原则，只处理当前任务直接相关的内容，不顺手重构、格式化或抽象无关代码。

## Documentation

- 文档目录职责、归档规则和流转说明统一参考 `docs/README.md`。
- 进入具体规范前，先通过 `docs/README.md` 判断文档位置；只按需读取和当前任务相关的细则。
- 在首次编辑文件前完成必要规范读取；如果任务范围扩大，再补读新增范围对应规范。
- 涉及前端实现时，至少读取 `docs/frontend/standards/frontend-development.md`按照规范实现。

## Frontend Implementation

- 新增需求、新增页面或扩展既有功能时，按实际涉及范围读取 `docs/frontend/README.md` 分流到 `architecture/`、`standards/`、`components/` 或 `guides/` 后执行。
- 涉及 UI、组件、表单、列表、详情、交互状态或组件拆分时，追加读取 `docs/frontend/components/components.md`、`docs/frontend/components/component-splitting.md` 和 `docs/frontend/standards/file-organization.md`。
- 新增页面时，route page entry 只承担路由参数、页面级 composition、状态归属和数据流编排；独立 UI 区块按 `docs/frontend/` 规范下沉为命名组件。
- 实现前先确认 entry、state ownership、data flow、interaction flow 和 stable UI boundaries，再决定组件拆分、目录放置和需要补读的规范。
- 模板默认启用 theme 和 i18n；相关实现沿用现有基座，细则见 `docs/frontend/guides/theming-and-i18n.md`。
- 仅在用户明确要求时移除 theme 或 i18n，并同步更新实现、依赖、测试和文档。

## Constraints

- 开发阶段只做最小必要检查，不主动执行 `dev server`、`build`、`deploy`、`publish` 等高副作用命令。
- 未经用户明确要求，不执行 `git add`、`git commit`、`git push`。
- 不修改、回滚、覆盖或提交与当前任务无关的文件，尤其是 dirty worktree 中已有用户改动。

## Test Scope

- 只为主要逻辑维护测试：业务规则和分支、状态转换、数据转换与错误归一化、失败恢复、权限/路由结果，以及被多个模块依赖的公共契约。
- 纯展示组件、固定文案与翻译资源、第三方库初始化、简单 getter/setter、常量、直接映射和只断言静态文案的 smoke test 默认不新增或保留。
- 修改没有形成独立行为或风险边界时，不为了测试覆盖率机械新增 test；类型和静态约束能充分覆盖的内容优先交给 TypeScript 和 ESLint。
- 需要测试时，默认运行目标模块的相邻测试；公共契约改变时追加直接消费者测试；跨 router/provider/error boundary 等边界时再增加最小集成测试。
- 影响 JSX、hook 依赖、import、公共 API 或类型契约时，对受影响文件运行 ESLint，并执行一次项目级 `pnpm typecheck`；不要用 `tsc <file>` 代替项目 typecheck。
- 影响范围无法可靠收窄，或修改共享基础设施的多个行为边界时运行 `pnpm test`；不要因为存在 `test` 脚本就无条件运行全量测试。
- 修改 `package.json`、Vite、TypeScript、ESLint、Prettier 或跨层规则时运行 `pnpm check`；`pnpm check` 不包含 build。
- 只修改 Markdown/YAML 文档时，不运行前端单测；按范围运行 `pnpm format:check`、Manager validator 或 repair validator。
- 只修改 CSS 且不改变 DOM 或交互时，不要求单测；检查响应式、文本溢出、focus、主题和必要 UI 状态。
- Bug 修复必须运行能复现问题的回归测试；没有合适测试时，为用户可观察的主要逻辑补最小测试。

常用范围命令：

```bash
# 主要逻辑对应的一个或多个测试文件
pnpm exec vitest run path/to/a.test.ts path/to/b.test.tsx

# 无法安全收窄影响范围
pnpm test

# 工程配置或跨模块基础设施
pnpm check
```

## Delivery

- 交付时说明本次修改范围，以及已执行或未执行的验证。
- 如果验证因缺少依赖、脚本或用户授权无法执行，必须明确说明。
