# UI Component Inventory

## 文档定位

本文档记录当前项目已经落地的 UI 组件统计、职责、复用边界和替代关系。组件治理规则见 `docs/frontend/components/components.md`。

不收录范围：

- `src/app/*` 下的 app shell、provider、router 入口。
- `src/pages/*/*Page.tsx` 这类 route page entry。
- 纯配置、hook、API、测试工具和样式入口。

## 当前统计

| Layer                | Count | Notes                               |
| -------------------- | ----: | ----------------------------------- |
| `src/shared/ui/`     |     0 | 当前模板未内置 shared UI 组件       |
| `src/entities/*/ui/` |     0 | 当前模板未内置 entity 组件          |
| `src/features/*/ui/` |     0 | 当前模板未内置 feature 组件         |
| `src/widgets/*/ui/`  |     0 | 当前模板未内置 widget 组件          |
| `src/pages/*/ui/`    |     0 | 当前模板未内置 page-private UI 组件 |

## 组件清单

| Component | Layer | Path | Status | Responsibility | Used By | Notes |
| --------- | ----- | ---- | ------ | -------------- | ------- | ----- |

当前模板没有已落地的 UI 组件需要登记。`App`、`AppProviders`、`AppRouter` 和 `HomePage` 属于应用入口、路由入口或页面入口，不写入组件清单。

## shared UI 状态

当前模板未内置 `src/shared/ui/` 组件。使用方项目只有在组件已经落地、无业务语义、并形成稳定复用后，再按本清单格式登记。
