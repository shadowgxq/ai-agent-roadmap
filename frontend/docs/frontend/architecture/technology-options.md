# Technology Options

## 文档定位

本文档记录通用前端项目的技术基线、架构边界、目录分层和依赖方向。它是模板规范，不绑定具体业务域。

## 默认技术基线

模板默认适用于：

- `React`
- `TypeScript`
- `Vite`
- `pnpm`

默认工程文件采用兼容优先的稳定基线：`React 18`、`Vite 6`、`TypeScript 5`、`Node >=20.19`。

## 默认预装但不强制的工程选项

以下依赖是当前公司模板的默认初始化选型，会进入模板 `package.json` 和最小源码骨架。它们不是业务项目的强制约束；使用方项目可以按团队约定删除、替换或扩展，但应保持集中配置和分层边界清晰。

| 领域            | 默认选型                                   | 模板入口                          | 说明                                                                   |
| --------------- | ------------------------------------------ | --------------------------------- | ---------------------------------------------------------------------- |
| Routing         | `react-router-dom`                         | `src/app/router/`                 | 使用集中 route config，避免页面内散落路由定义。                        |
| Server state    | `@tanstack/react-query`                    | `src/app/providers/`              | 管理请求、缓存、loading、error、retry、invalidation。                  |
| Client UI state | `zustand`                                  | 按需创建 store                    | 只管理跨组件但不属于服务端的数据。                                     |
| HTTP request    | `axios`                                    | `src/shared/api/requestClient.ts` | 页面和组件不直接散落请求细节。                                         |
| Styling         | CSS Modules + CSS Variables                | `src/shared/styles/`              | 样式隔离和 token 统一。                                                |
| UI primitive    | Radix UI 基础包                            | `src/shared/ui/`                  | 业务层不直接散用底层 primitive API，应先封装 project-owned shared UI。 |
| Icons           | `lucide-react`                             | `src/shared/icons/`               | 提供基础图标出口，并预留业务自定义图标库导入位置。                     |
| className       | `clsx`                                     | 按需使用                          | 用于条件 className 拼接。                                              |
| Animation       | `gsap`                                     | 按需使用                          | 用于复杂编排和运行时可控动画，并尊重 `prefers-reduced-motion`。        |
| Theming         | CSS Variables + `data-theme`               | `src/shared/theme/`               | 默认启用 light/dark，不额外引入主题框架。                              |
| i18n            | `i18next` + `react-i18next`                | `src/shared/i18n/`                | 默认启用并提供 en/zh 资源和语言持久化。                                |
| Testing         | `vitest` + React Testing Library + `jsdom` | `src/shared/testing/`             | 提供默认单测和组件测试基线。                                           |

## 业务边界

模板只定义通用前端工程边界，不定义具体业务域。

以下内容不应写入通用模板：

- 具体产品、行业或业务对象。
- 具体页面需求、用户路径和验收标准。
- 具体后端接口契约、错误码和联调记录。
- 具体权限、计费、角色、审批、工作流等业务规则。

使用模板初始化项目后，上述内容应进入使用方项目自己的 `docs/prd/`、`docs/api/`、`openspec/specs/` 或对应业务文档目录。

## `src/` 目录分层

推荐建立以下工程化 `src/` 结构：

```text
src/
  main.tsx
  app/
    providers/
    router/
  pages/
  widgets/
  features/
  entities/
  shared/
    api/
    config/
    hooks/
    icons/
    styles/
    testing/
    ui/
    utils/
```

| 路径                  | 作用                                                              | 模板默认状态                     |
| --------------------- | ----------------------------------------------------------------- | -------------------------------- |
| `src/main.tsx`        | 应用启动入口，挂载 React root，引入全局样式                       | 已提供                           |
| `src/app/`            | 应用装配层，放 root、providers、router 和全局错误边界             | 已提供                           |
| `src/app/providers/`  | 全局 Provider 聚合，例如 query、theme、auth、i18n                 | 已接入 query、theme 和 i18n      |
| `src/app/router/`     | 集中路由配置和 route-level 装配                                   | 已接入 `react-router-dom` 根路由 |
| `src/pages/`          | 页面入口层，只做 route-level composition                          | 已提供 `home` 示例               |
| `src/widgets/`        | 页面级复合区块，例如 navigation panel、header bar、action toolbar | 按需使用                         |
| `src/features/`       | 用户动作和业务流程                                                | 按需使用                         |
| `src/entities/`       | 领域对象、领域类型、领域展示和领域级 hook                         | 按需使用                         |
| `src/shared/`         | 无业务通用能力集合                                                | 部分提供                         |
| `src/shared/api/`     | request client、API error normalization、query client base config | 已提供 `requestClient`           |
| `src/shared/config/`  | typed runtime config、环境变量转换和项目级常量                    | 已提供 API runtime config        |
| `src/shared/hooks/`   | 与业务无关的通用 hook                                             | 按需使用                         |
| `src/shared/icons/`   | 图标资产、图标 wrapper 和图标名称约束                             | 已提供基础图标出口               |
| `src/shared/styles/`  | reset、global、CSS Variables 和 theme tokens                      | 已提供 global styles 和 tokens   |
| `src/shared/testing/` | 测试工具、render helper 和 mock helper                            | 已提供测试 setup                 |
| `src/shared/ui/`      | 无业务基础 UI 组件                                                | 按需使用                         |
| `src/shared/utils/`   | 与业务无关的通用工具函数                                          | 按需使用                         |

## 依赖方向

```text
app -> pages -> widgets -> features -> entities -> shared
```

分层规则：

- `app` 可以 import 其他层，但只做应用装配。
- `pages` 可以 import `widgets`、`features`、`entities`、`shared`。
- `widgets` 可以 import `features`、`entities`、`shared`。
- `features` 可以 import `entities`、`shared`。
- `entities` 只能 import `shared`。
- `shared` 不能 import `app`、`pages`、`widgets`、`features`、`entities`。

## 数据流边界

推荐数据流：

```text
UI event
  -> feature action
  -> query/mutation hook
  -> API module
  -> shared request client
  -> backend
```

组件不直接创建 request client，不直接散落接口请求细节。server state 不放入 client UI store。
