# 换肤与 i18n（theming & i18n）

模板默认预装并启用两项基座能力：**换肤**（light / dark）和 **i18n**（多语言）。
Agent 默认沿用现有接线。使用方项目可以显式替换或移除，但应把它作为项目基线变更，一次性同步源码、调用方、依赖、测试、模板骨架和规则文档。

## 换肤（无需额外主题框架）

基于 CSS 变量 + `<html data-theme>`，复用模板已有的 zustand 做状态持久化，不额外引入主题框架。

- token：`src/shared/styles/tokens.css` 的语义色在 `:root`（light）与 `[data-theme='dark']` 两套之间切换。
- 状态：`src/shared/theme/theme-store.ts`，zustand + `persist`，state `{ mode: 'light' | 'dark' }`，localStorage key `ui-theme`。
- 初始值：没有有效持久化值时读取一次 `prefers-color-scheme`，之后只保留用户显式选择的 light/dark。
- 生效：`src/app/providers/ThemeInitializer.tsx` 订阅 store，把当前 mode 写入 `document.documentElement.dataset.theme`。
- 防闪烁：`index.html` 内联脚本在首帧前读取持久化主题并预设 `data-theme`。
- 消费：组件用 `useTheme()`（`{ mode, setMode, toggle }`）读取和切换。

样式只需引用语义色 token（`var(--color-*)`），深浅两套自动生效，**不要在业务代码里按主题写分支**。

### 新增一个主题 token

在 `tokens.css` 的 `:root` 加默认值，并在 `[data-theme='dark']` 加对应覆盖值；随主题变化的放语义色区，固定值（间距/圆角/排版）放 primitive 区、无需在 dark 覆盖。

## i18n（react-i18next）

- 实例：`src/shared/i18n/instance.ts`，`i18next.createInstance()` + `initReactI18next`，`fallbackLng: 'en'`，初始语言从持久化读取。
- 资源：`src/shared/i18n/locales/{en,zh}.json`。
- 状态：`src/shared/i18n/locale-store.ts`，zustand + `persist`（key `ui-locale`），`setLocale` 内同步调用 `i18n.changeLanguage`。
- 装配：`src/app/providers/AppProviders.tsx` 用 `<I18nextProvider>` 包裹。
- 消费：组件文案用 `useTranslation()` 的 `t('key')`；切换语言用 `useLocale()`（`{ locale, setLocale, available }`）。

与换肤统一采用「zustand persist」一个模式，便于对齐。

### 新增一种语言

1. 新增 `src/shared/i18n/locales/<lang>.json`（键与现有语言对齐）。
2. 在 `instance.ts` 的 `resources` 与 `SUPPORTED_LOCALES` 加入该语言。

### 新增文案

在各 `locales/*.json` 补同名 key，组件用 `t('新增.key')` 引用；不要在 JSX 里硬编码可见文案。

## opt-out（项目基线变更）

不要把 opt-out 当成删除单个目录的局部修改。执行前先搜索全部 import、provider、测试和演示调用；修改后至少运行 typecheck 和相关测试。

- **移除换肤**：先删除或改写 `DemoControls` 等主题调用方，再删除 `src/shared/theme/`、`src/app/providers/ThemeInitializer.tsx` 和 `index.html` 内联脚本；从 `AppProviders` 去掉 `<ThemeInitializer/>`，清理主题测试和 dark token，仅保留确定使用的一套语义 token。
- **移除 i18n**：先把 `HomePage`、`DemoControls`、`src/app/error/` 等调用方改为项目确认的文案方案，再删除 `src/shared/i18n/` 和相关测试；从 `AppProviders` 去掉 `<I18nextProvider>`，最后卸载 `i18next`、`react-i18next`。
- **移除演示控件**：删除 `src/pages/home/components/DemoControls.*` 并从 `HomePage` 去掉引用；只移除 theme 或 i18n 时，也必须先处理该组件对两项能力的联合依赖。
- **同步项目规则**：更新 `AGENTS.md`、`README.md`、`docs/frontend/standards/frontend-development.md`、本指南和依赖清单，避免 Agent 继续按已移除的基线实现。
