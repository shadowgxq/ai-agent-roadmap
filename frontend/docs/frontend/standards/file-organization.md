# File Organization

目录、文件命名和放置规则。

## 文件命名

- 模块目录：`kebab-case`。
- React component：`PascalCase.tsx`；样式文件：`ComponentName.module.css`。
- hook：`useXxx.ts`；store：`*.store.ts`。
- API：`*.api.ts`；query hook：`*.queries.ts`；mutation hook：`*.mutations.ts`。
- 类型：`*.types.ts`；常量：`*.constants.ts`；工具：`*.utils.ts`。
- 测试：`*.test.ts` 或 `*.test.tsx`。
- 枚举值、typed options、label/tone/icon mapping 放拥有该语义的 `*.constants.ts`；对应 union type 放 `*.types.ts` 或就近导出。

## 组件目录

命名 UI 组件默认使用目录包裹：

```text
ComponentName/
  ComponentName.tsx
  ComponentName.module.css
  index.ts
```

- 组件实现入口必须是 `<ComponentName>.tsx`。
- `index.ts` 只做公开出口，不写组件、hook、工具函数或类型实现。
- 禁止用 `index.tsx` 作为组件实现文件。
- 简单 JSX 且只有一个调用点时不要提前抽组件；已经抽成命名组件就按目录放置。
- `App`、providers、router、page route entry 保持在模块根目录，不算 UI 组件 inventory。

## 放置规则

- 当前页面私有组件：`pages/<page-name>/ui/`。
- 当前页面级区块组件：`widgets/<widget-name>/ui/`。
- 用户动作或业务流程组件：`features/<feature-name>/ui/`。
- 领域对象展示或轻量编辑组件：`entities/<entity-name>/ui/`。
- 无业务基础组件：`shared/ui/`。
- 不因“未来可能复用”提前移动到 `shared/ui` 或 `shared/hooks`。

## Module API

- 跨模块 import 走模块公开出口 `index.ts`。
- 同模块内部可用相对路径访问内部文件。
- `index.ts` 默认 named export，避免无选择地 `export *`。
- 同模块内部不要从自己的 `index.ts` 回流 import。
- 跨 slice 只能访问对方公开出口，不能深读 `api/`、`model/`、`ui/`。
- 同层 slice 默认不互相依赖；需要组合时上移到 `widgets`、`pages` 或更明确的上层模块。
- public `index.ts` 不聚合重型模块；编辑器、图表、导出能力保持独立入口并按需动态加载。

## Hook 和逻辑

- 少量组件内部交互状态直接写在组件内。
- 只服务当前组件的 hook 放组件同目录。
- 当前模块多个组件共享的 hook 放所属模块 `model/`。
- 用户动作相关 hook 放 `features/<feature-name>/model/`。
- 领域对象相关 hook 放 `entities/<entity-name>/model/`。
- 无业务通用 hook 才放 `shared/hooks/`。
- query key、query hook、mutation hook、selector 放拥有对应数据或动作语义的模块内。
- debounce input、deferred search、keyboard shortcut、global listener 等 hook 先就近放置；两个以上稳定无业务场景再上移。

## shared 子目录

```text
shared/
  api/       # request client、error normalization、query client base config
  config/    # 环境配置和项目级常量
  hooks/     # 无业务通用 hook
  icons/     # 图标资产、wrapper、名称约束
  styles/    # reset、global、token、theme
  testing/   # render helper、mock helper、测试工具
  ui/        # 无业务基础 UI
  utils/     # 无业务纯工具函数
```

- debounce、throttle、once、idempotency 只有完全无业务时才放 `shared/utils/`。
- `shared/hooks/` 不能依赖业务 API、业务 store、route 结构或业务文案。
- 业务常量放拥有该语义的 feature、entity 或 page，不提前放 `shared/config/`。

## 测试和配置

- 组件私有测试放组件同目录。
- model、API、selector、DTO 转换测试放对应文件旁边。
- 枚举转换、未知值 fallback、typed mapping、action guard 要就近测试。
- shared testing 只放跨模块复用能力，不放业务 fixture。
- 环境变量读取和转换集中在 `shared/config/`。
