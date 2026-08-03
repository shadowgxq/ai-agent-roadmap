# Frontend Standards

`standards/` 保存前端实现硬规则。这里只做编码、组件 API、文件组织、UI 状态和可访问性约束。

不在这里写：

- 组件是否抽取、放哪一层、是否登记清单：看 `docs/frontend/components/components.md`。
- 拆分案例和反例：看 `docs/frontend/components/component-splitting.md`。
- 已落地组件事实：看 `docs/frontend/components/component-inventory.md`。
- 技术选型、依赖方向、`src/` 架构边界：看 `docs/frontend/architecture/technology-options.md`。

## 文件索引

| 文件                             | 什么时候看                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------------- |
| `frontend-development.md`        | 日常前端实现入口：命名、类型、枚举、React、import、状态、交互防重、样式、配置和验证 |
| `component-definition.md`        | 已决定要写组件后，查看 props、可控/非可控、行为、数据边界和 shared primitive API    |
| `file-organization.md`           | 判断文件命名、组件目录、module API、hook/model/test/config 放置                     |
| `accessibility-and-ui-states.md` | 处理 loading、empty、error、disabled、pending、表单、浮层、键盘和响应式文本         |

## 读取顺序

1. 前端实现任务先看 `frontend-development.md`。
2. 涉及组件 API 或 shared primitive 时看 `component-definition.md`。
3. 涉及放置路径或文件命名时看 `file-organization.md`。
4. 涉及交互状态、表单、浮层、键盘或响应式文本时看 `accessibility-and-ui-states.md`。

## 维护原则

- 每个具体规则只放一个文件，其他文件只引用，不复制。
- `README.md` 只做入口索引和边界说明，不承载细则。
- 新增、删除或改名 standards 文件时，同步更新本文件、`docs/frontend/README.md` 和 `docs/README.md`。
