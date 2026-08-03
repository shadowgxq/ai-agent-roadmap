# Frontend Development

日常前端实现入口。架构边界看 `docs/frontend/architecture/technology-options.md`；组件、目录和 UI 状态细则看本目录其他文件。

## 命名和类型

- 命名表达业务含义，避免 `data`、`info`、`temp`、`common`、`misc`。
- Boolean 用 `is`、`has`、`can`、`should`；事件 props 用 `onXxx`，内部 handler 用 `handleXxx`。
- 集合用复数名；映射结构用语义后缀，例如 `entityById`、`resourceMap`、`selectedIdSet`。
- 不使用 `any`；不确定类型先用 `unknown` 并在边界收窄。
- props、hook 参数、API response、store state、对外函数返回值都要有明确类型。
- API DTO 用 `Dto` 后缀；DTO 不直接贯穿 UI，在 API/model 边界转成 domain type。

## 枚举和字面量集合

- status、mode、variant、tab、filter key 等有限集合，默认用 `as const` 推导 union type。
- 默认不新增 TypeScript `enum`；只有后端契约、生成 SDK、数字枚举或运行时互操作明确需要时才使用。
- API enum/字典值进入 UI 前必须转换并兜底未知值，不直接 `as DomainType`。
- label、icon、tone、order、disabled reason 等枚举派生信息集中维护，用 `Record<Union, Value>` 或 typed options，并配合 `satisfies` 保证覆盖完整。
- `switch` 处理 union 要保持穷尽，让新增枚举值能触发类型提示。

## React

- render 必须纯净：不请求、不订阅、不写 store、不改 DOM、不发 analytics、不启动 timer。
- 能从 props、state、query result、URL 参数推导的值，不放进 state，也不用 effect 同步。
- `useEffect` 只同步外部系统；用户动作副作用放 event handler、mutation 或 feature action。
- state 保持最小单一来源；基于旧 state 更新时用 functional setState。
- 不在组件内部定义子组件；静态 options、mapping、JSX、RegExp 提升到模块作用域。
- `useMemo`、`useCallback` 只为稳定依赖、memoized 子组件或明确性能问题使用。
- 昂贵输入派生优先用 `useDeferredValue` + `useMemo`；非紧急大量 UI 更新可用 `startTransition`。

## Import 和 Bundle

- 跨模块 import 走公开出口 `index.ts`；同模块内部可以用相对路径。
- `shared` 不能 import 业务层；同层 slice 默认不互相 import。
- 跨 slice 不读对方内部文件；需要组合时上移到 `widgets` 或 `pages`。
- 大型第三方库避免宽泛 import；只在用户触发后才需要的大模块用动态 `import()`。
- import 路径保持静态可分析，不拼动态字符串。

## 状态和数据

- server state 用 `@tanstack/react-query` 或项目确认的缓存方案，不放 client UI store。
- client UI store 只放跨组件、非服务端、不可由 URL/query 推导的状态；组件用 selector 读取最小状态。
- 可分享、可恢复、影响浏览器导航的筛选、分页、搜索、tab 状态优先放 URL。
- 表单草稿默认放局部 state；只有跨页面或跨流程恢复才上移。
- query key 必须稳定、可序列化，并包含影响请求结果的参数。
- mutation 成功后必须明确 cache invalidation、cache update 或重新获取策略。
- 多个互不依赖的异步请求并行执行。
- 只在 callback 中使用的动态值不要提前订阅，在 handler 内按需读取。

## 交互和重复触发

- submit、save、delete、pay、publish 等一次性动作，用 `pending + disabled + action guard` 防重复。
- 防重复逻辑放在 action 或 form `onSubmit` 边界，不能只保护 button `onClick`。
- `debounce` 不作为提交防重主手段；强幂等动作还需要 mutation pending、幂等键或服务端保护。
- `debounce` 只用于 search、autosave、resize、scroll、drag 等高频事件，并明确 leading/trailing、等待时间和取消策略。
- debounced/throttled handler 在卸载或依赖变化时必须取消未执行任务。
- 同一动作被按钮、快捷键、菜单项触发时，复用同一个 action guard。
- scroll、touch、wheel 等全局高频监听优先 passive，并避免每个组件实例重复注册。

## 样式和配置

当前模板默认启用 theme 和 i18n；保留这些能力时，下面的主题和文案规则属于项目硬规则。使用方项目如需 opt-out，必须按 `guides/theming-and-i18n.md` 完整移除并同步更新项目规则，不能只删除局部接线。

- 样式优先用项目 token、CSS Modules 和 `src/shared/styles/tokens.css` 的 `--color-*`。
- 重复颜色、间距、z-index、圆角沉淀为 token；条件 className 用 `clsx`。
- token 分类：颜色 `--color-*`、间距 `--space-1..8`、圆角 `--radius-*`、排版 `--font-size-*`/`--leading-*`/`--font-weight-*`、层级 `--z-*`、阴影 `--shadow-*`。
- 语义色随主题变化：`:root` 为 light，`[data-theme='dark']` 覆盖；样式只引用语义色 token，不在业务代码里按主题写分支。换肤与多语言细则见 `guides/theming-and-i18n.md`。
- 响应式断点约定为常量（不落 token）：sm 480px / md 720px / lg 1024px / xl 1280px，避免魔法数值散落。
- 用户可见文案走现有 i18n 接线：React 组件使用 `useTranslation()` 的 `t()`，非组件边界使用项目导出的 i18n instance；不在 JSX 里硬编码。
- 文本在移动端和桌面端都不能溢出容器。
- 运行时配置集中在 `src/shared/config/`；客户端只读取 `VITE_*`，并在 config 边界完成类型转换和默认值处理。
- 前端代码不硬编码密钥、内部 token 或只能由服务端持有的配置。

## 验证

- 类型改动：跑 typecheck。
- 样式/组件改动：检查状态、响应式和文本溢出。
- shared UI 改动：检查至少两个使用场景。
- 数据流改动：检查 loading、error、empty、pending、cache 更新。
- 提交交互改动：检查连续点击、键盘提交、pending disabled、失败恢复。
- debounce/throttle 改动：检查取消、过期响应、卸载后不更新状态。
- 枚举/字典改动：检查未知值 fallback、映射覆盖、穷尽提示。
- 测试优先覆盖用户可观察行为；纯工具、DTO 转换、error normalization、复杂 selector 补单测。
