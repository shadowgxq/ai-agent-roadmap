# Frontend Docs

`docs/frontend/` 保存长期有效的前端工程规范、组件维护说明和模板落地指南。这里是前端文档入口，用来判断应该继续读取哪个细则文件。

## 目录

| 目录            | 作用                                                        |
| --------------- | ----------------------------------------------------------- |
| `architecture/` | 技术基线、架构边界、`src/` 分层、依赖方向和数据流边界       |
| `standards/`    | 日常编码、组件、文件组织、样式、UI 状态和可访问性规范       |
| `components/`   | UI 组件治理指南、组件统计清单、职责边界、复用判断和替代关系 |
| `guides/`       | 基于模板创建新项目、已有项目迁入清单、换肤与 i18n 使用说明  |

## Guides 文档

| 文件                                | 作用                                           |
| ----------------------------------- | ---------------------------------------------- |
| `guides/project-bootstrap.md`       | 新项目初始化、已有项目迁入和使用方项目补充清单 |
| `guides/theming-and-i18n.md`        | light/dark 换肤、i18n 接线、扩展和 opt-out     |
| `guides/runtime-config-and-vite.md` | typed runtime config、开发代理和拆包规则       |

## Components 文档

| 文件                                | 作用                                                               |
| ----------------------------------- | ------------------------------------------------------------------ |
| `components/components.md`          | UI 组件治理入口，提供分层、复用/新增、登记维护和后续阅读索引       |
| `components/component-splitting.md` | UI 组件拆分案例库，说明何时拆组件、拆 hook、拆 utility、放到哪一层 |
| `components/component-inventory.md` | 已落地 UI 组件统计和清单，只记录稳定事实，不写未落地设想           |

## Standards 文档

| 文件                                       | 作用                                                                                    |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| `standards/README.md`                      | 前端 standards 入口，说明文件索引、读取顺序和与 components/architecture 的边界          |
| `standards/frontend-development.md`        | 日常前端实现规则，覆盖命名、类型、枚举、React、import、状态、交互防重、样式、配置和验证 |
| `standards/component-definition.md`        | 单个组件的 props、可控/非可控、行为、数据边界和 shared primitive API                    |
| `standards/file-organization.md`           | 文件命名、组件目录、module API、hook/model/test/config 放置                             |
| `standards/accessibility-and-ui-states.md` | UI 状态、表单、浮层、ARIA、键盘、响应式文本和可访问性硬规则                             |

## 维护规则

- 只把长期稳定的前端规则写入 `docs/frontend/`。
- 具体业务需求、用户路径和验收标准写入使用方项目的 `docs/prd/`。
- 接口契约、错误码、mock 和联调说明写入使用方项目的 `docs/api/`。
- 临时执行计划、当前任务状态和批次编排不要写入 `docs/frontend/`。
- 当目录职责、读取顺序或文件命名变化时，同步更新本文件和 `docs/README.md`。
