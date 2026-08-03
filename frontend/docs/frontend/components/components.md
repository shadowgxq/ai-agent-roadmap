# Components

## 文档定位

本文档是 UI 组件治理入口，用来判断“该不该抽组件、放到哪一层、是否复用或新增、是否需要登记”。它只写长期有效的决策规则，不承载大量案例、目录细则或当前组件清单。

按需继续阅读：

| 需求                                                                   | 文档                                                     |
| ---------------------------------------------------------------------- | -------------------------------------------------------- |
| 判断怎么拆组件、拆 hook 还是 utility、看案例和反例                     | `docs/frontend/components/component-splitting.md`        |
| 查看当前已落地 UI 组件统计和清单                                       | `docs/frontend/components/component-inventory.md`        |
| 查看组件 props、可控/非可控、状态表达、数据边界和 shared primitive API | `docs/frontend/standards/component-definition.md`        |
| 查看目录、文件命名、barrel export 和模块放置细则                       | `docs/frontend/standards/file-organization.md`           |
| 查看 loading、empty、error、disabled、focus 和可访问性规则             | `docs/frontend/standards/accessibility-and-ui-states.md` |

## 核心判断

先问三个问题：

1. 这是不是一个稳定 UI 边界？
   有清晰名称、独立状态、可访问性交互、重复结构或独立测试价值，才考虑抽组件。只是为了减少几行 JSX，不抽。

2. 它属于哪个业务层级？
   根据真实职责放到 page-private UI、widget、feature、entity 或 shared UI，不默认放进 `shared/ui`。

3. 它是否已经稳定复用？
   当前只服务一个页面或业务流时先就近放置；至少两个稳定场景复用，且能去掉业务语义后，才考虑提升层级或抽成 shared UI。

## 分层索引

| 层级            | 目录                 | 适合放什么                                                      | 不放什么                                      |
| --------------- | -------------------- | --------------------------------------------------------------- | --------------------------------------------- |
| shared UI       | `src/shared/ui/`     | 无业务、跨模块复用的基础 UI，例如 `Button`、`Dialog`、`Tooltip` | 业务流程、领域字段、页面文案、接口 DTO        |
| entities        | `src/entities/*/ui/` | 领域对象展示、轻量编辑、状态呈现                                | 跨领域业务流程、页面布局                      |
| features        | `src/features/*/ui/` | 用户动作、业务流程、可独立触发的交互                            | 纯展示壳、路由组合                            |
| widgets         | `src/widgets/*/ui/`  | 页面级复合区域，例如 sidebar、toolbar、header                   | 底层通用 primitive                            |
| page-private UI | `src/pages/*/ui/`    | 只服务当前页面的局部 UI                                         | route page entry、可复用基础 UI、复杂业务模型 |

不进入组件清单：

- `src/app/*` 下的 app shell、providers、router。
- `src/pages/*/*Page.tsx` 这类 route page entry。
- 纯配置、hook、API、测试工具和样式入口。

## 目录约定

一旦抽成命名 UI 组件，统一使用 `ComponentName/` 目录：

```text
ComponentName/
  ComponentName.tsx
  ComponentName.module.css
  index.ts
```

后续新增类型、常量、测试、story、组件私有 hook 或子组件时，继续放在同一个 `ComponentName/` 目录内。具体结构见 `docs/frontend/standards/file-organization.md`。

## 复用还是新增

新增组件前按顺序判断：

1. 是否已有同类组件可以直接复用。
2. 是否只缺少小能力，可以兼容扩展现有组件。
3. 是否只服务当前页面或当前业务流，可以先就近新增。
4. 是否已经有两个以上稳定使用场景，值得提升层级。
5. 是否完全无业务语义，值得进入 `shared/ui`。

| 选择                         | 适用条件                                 |
| ---------------------------- | ---------------------------------------- |
| 直接复用                     | 视觉、交互和状态边界基本一致             |
| 兼容扩展                     | 只缺少小能力，且不会破坏现有调用         |
| 就近新增                     | 当前场景明确，但复用价值还没有成立       |
| 提升到 entity/feature/widget | 多个同类场景复用，但仍带领域或业务语义   |
| 抽到 shared UI               | 无业务语义、跨模块稳定复用、API 边界清晰 |

补充判断：

- 只共享视觉时，优先抽 token、样式变量或基础 primitive。
- 只共享枚举文案、选项顺序或状态映射时，优先抽 typed constants/options，不必抽 UI 组件。

## 禁止项

- 不为相同 UI 平行新建多个近似组件。
- 不把页面文案、业务字段、权限模型或接口 DTO 泄漏进 `shared/ui`。
- 不为一次性设计稿、临时实验或不稳定业务组件登记 shared component。
- 不为只有一个调用点的简单 JSX 提前抽组件。
- 不让 UI 组件直接创建 request client 或散落接口请求细节。
- 不让中间组件只做 props tunneling，没有独立职责。

## 登记维护

组件已经落地并稳定使用后，更新 `docs/frontend/components/component-inventory.md`：

- 新增稳定 UI 组件时，补一行组件记录。
- 组件 API、职责、层级或使用场景变化时，同步更新清单。
- 组件废弃时，标记 `deprecated` 并写明替代组件和迁移方向。
- 未落地设想、临时组件和 route/app 入口不进入清单。

登记字段：

```text
| Component | Layer | Path | Status | Responsibility | Used By | Notes |
```

## 维护原则

- 本文档只做治理入口和决策规则。
- 大量拆分案例写入 `component-splitting.md`。
- 当前组件事实写入 `component-inventory.md`。
- 目录和命名细则写入 `standards/file-organization.md`。
- props、状态和可访问性细则写入对应 standards 文档。
- 规则变化时同步更新 `docs/frontend/README.md` 和 `docs/README.md` 的入口说明。
