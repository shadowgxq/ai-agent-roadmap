# Component Definition

单个组件的 API、行为、数据边界和 shared primitive 契约。

是否抽组件、放哪一层、何时进 `shared/ui`、是否登记组件清单，看 `docs/frontend/components/components.md`。

## 组件 API

- Component 用 `PascalCase`；Props 类型用 `ComponentNameProps`；默认 function component。
- Props 必须显式类型，不用 `any`；可复用组件支持 `className` 透传到 root。
- 事件 props 用 `onXxx`；内部 handler 用 `handleXxx`。
- Boolean props 用 `is`、`has`、`can`、`should`；集合 props 用复数。
- 多变体组件用 `variant`、`size`、`tone` 等枚举 props，避免多个互斥 Boolean。
- 枚举 props 使用命名 union type；可选值、label、样式映射从同一 typed source 派生。
- 复杂内容优先用 `children`、具名子组件或 render prop，不用大量 string props 拼 UI。
- 可控/非可控边界要清楚，避免 `value/onChange` 与 `defaultValue` 混成隐式双状态源。
- shared UI 需要 DOM 能力时按场景支持 ref 透传。

## 组件行为

- root element 优先语义化 HTML；交互元素用 `button`、`a` 或原生控件，不用 `div` 模拟。
- Button-like 组件必须支持 `disabled`，按需支持 `isPending`/`loading`，并保证 pending 时不重复触发。
- 接收 `onSubmit`、`onConfirm`、`onSave` 的组件，由调用方持有 mutation 状态，组件负责展示和阻止重复交互。
- 不在 render 内定义子组件、静态 options 或静态 mapping；提升到模块作用域或就近常量文件。
- 组件内部不缓存 props 副本，除非是明确的可编辑草稿或一次性初始化状态。

## 数据边界

- 组件不创建 request client，不散落接口请求细节。
- 请求进入 query hook、mutation hook 或对应 feature/entity 的 model 层。
- query hook 负责 loading、error、cache、retry；组件只消费 UI-ready 状态。
- mutation hook 或 feature action 负责 invalidation、cache update、toast、导航等后续动作。
- DTO 和 domain type 分开；请求参数、query key、DTO 转换逻辑就近维护。

## UI Primitive

- overlay、dialog、popover、tooltip、select、menu 优先复用项目 shared UI。
- 项目没有 shared UI 时，先建立最小基础封装，再让业务层使用。
- shared UI 封装可访问性、尺寸、token、常见状态，不把底层 primitive 细节泄漏给业务层。
- Button、MenuItem、DialogAction 等 action primitive 统一处理 `type`、`disabled`、pending、可访问名称和重复触发保护。

## 样式

- 组件样式使用 CSS Modules 或项目确认的样式体系。
- class 从结构语义命名，例如 `.root`、`.header`、`.content`、`.footer`、`.action`。
- 颜色、间距、圆角、字体优先 token；状态样式优先基于 `data-state`、`aria-invalid`、`disabled`。
- root element 不承担外部间距；外部布局由调用方或布局容器控制。
