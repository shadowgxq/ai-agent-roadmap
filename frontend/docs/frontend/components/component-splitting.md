# Component Splitting

## 文档定位

本文档定义 UI 组件拆分的判断方法、落地步骤、案例和反例。它补充 `docs/frontend/components/components.md`，用于在真实页面开发时判断“要不要拆、拆到哪一层、拆成组件还是 hook、是否进入 shared”。

外部参考：

- [React - Thinking in React](https://react.dev/learn/thinking-in-react)：从 UI mockup 识别组件层级、构建静态版本、最小化 state、找到 state owner。
- [React - Reusing Logic with Custom Hooks](https://react.dev/learn/reusing-logic-with-custom-hooks)：重复的 stateful logic 和 Effect 可以抽 custom hook，但不要为每一点重复都抽 hook。
- [Feature-Sliced Design - Slices and segments](https://fsd.how/docs/reference/slices-segments/)：按产品含义分 slice，按技术性质分 `ui`、`api`、`model` 等 segment，并保持高内聚、低耦合。
- [Storybook - Why Storybook?](https://storybook.js.org/docs/get-started/why-storybook)：组件应能通过 props、mock data 和 fake events 独立呈现关键状态。
- [Bulletproof React - Project Structure](https://github.com/alan2207/bulletproof-react/blob/master/docs/project-structure.md)：`app` 放应用入口，`features` 放功能模块，shared 只放跨应用复用能力，避免 feature 代码混入 shared component。

## 拆分目标

组件拆分不是为了减少行数，而是为了让职责、状态、复用和测试边界更清楚。

优先满足：

- 单一职责：一个组件只承担一个稳定 UI 角色。
- 高内聚：组件内部文件围绕同一个 UI 目标组织。
- 低耦合：组件不依赖不该知道的 feature、route、API DTO 或 app context。
- 可组合：上层组合下层，下层不反向知道上层业务流程。
- 可隔离验证：关键状态可以通过 props、mock data 或 fake events 独立呈现。

## 拆分前检查

每次准备抽组件前，先回答：

| 问题                                        | 如果答案是 yes                                               | 建议                              |
| ------------------------------------------- | ------------------------------------------------------------ | --------------------------------- |
| 这段 JSX 是否已有清晰业务或 UI 名称？       | 例如 `OrderSummary`、`FilterToolbar`、`EmptyState`           | 可以考虑抽组件                    |
| 这段 JSX 是否会被独立维护状态、交互或测试？ | 有独立 loading、empty、error、disabled、focus、keyboard 行为 | 倾向抽组件                        |
| 这段 JSX 是否只是 5 行静态标签？            | 没有独立语义和交互                                           | 先留在父组件                      |
| 抽出后是否会产生 6 个以上透传 props？       | 子组件只是在传话                                             | 先调整 state owner 或保留在父组件 |
| 是否只是因为父组件“看起来长”？              | 但没有清晰边界                                               | 先整理数据结构、局部函数或 hook   |
| 是否已经有两个以上稳定使用场景？            | 视觉和行为边界基本一致                                       | 可以考虑提升层级或进入 shared     |

## 拆分流程

1. 先按 UI 层级画边界。
   找出页面中的稳定区域、列表项、工具栏、弹窗、空态、表单区块和可重复项。

2. 再按状态归属确认边界。
   state 放在需要读取和修改它的最近公共父级；只影响单个局部交互的 state 留在组件内。

3. 决定拆成组件、hook 还是 utility。
   JSX 和可访问性交互边界拆组件；stateful logic 或 Effect 拆 hook；纯计算拆 utility。

4. 决定放置层级。
   只服务当前页面放 `pages/<page-name>/ui/ComponentName/`；属于用户动作放 `features/*/ui/`；属于领域对象放 `entities/*/ui/`；页面级复合区域放 `widgets/*/ui/`；无业务、跨模块稳定复用才放 `shared/ui/`。

5. 保持目录一致。
   一旦抽成命名 UI 组件，就使用 `ComponentName/ComponentName.tsx`、`ComponentName.module.css`、`index.ts`。

## 拆分信号

适合拆组件：

- 出现稳定 UI 名词，且父组件已经在描述太多区域。
- 同一区域存在独立的 loading、empty、error、disabled、readonly 或 pending 状态。
- 列表项、表格行、卡片、菜单项、表单字段组等重复结构需要单独命名。
- 弹窗、popover、dropdown、toolbar、sidebar section 等交互区域有自己的焦点和键盘边界。
- 子树可以通过 props 和 event handlers 独立渲染。
- 视觉或交互会被 Storybook/story、截图测试或单元测试覆盖。

不适合拆组件：

- 只是为了让父组件少几行。
- 子组件没有清晰名称，只能叫 `Content`、`Wrapper`、`Block`。
- 抽出后需要传入大量父组件内部细节。
- 子组件只调用一个父级回调，再把所有字段透传给更深层。
- 组件内部直接请求 API、创建 request client 或消费 route 之外的隐式上下文。
- shared component 需要知道业务字段、业务状态机或接口 DTO。

## 放置决策表

| 场景                             | 放置位置                                        | 示例                                       |
| -------------------------------- | ----------------------------------------------- | ------------------------------------------ |
| 只服务某个页面的筛选条           | `src/pages/resource-list/ui/ResourceFilterBar/` | `ResourceFilterBar`                        |
| 页面内重复列表项，但不跨页面复用 | `src/pages/resource-list/ui/ResourceListItem/`  | `ResourceListItem`                         |
| 页面级 sidebar、header、toolbar  | `src/widgets/<widget-name>/ui/`                 | `WorkspaceSidebar`、`DatabaseToolbar`      |
| 某个用户动作或流程               | `src/features/<feature-name>/ui/`               | `InviteUserDialog`、`DeleteResourceButton` |
| 某个领域对象展示或轻量编辑       | `src/entities/<entity-name>/ui/`                | `UserAvatar`、`ResourceStatusBadge`        |
| 完全无业务的基础 UI              | `src/shared/ui/`                                | `Button`、`Dialog`、`Tooltip`              |
| 数据请求、mutation、cache        | `api/` 或 `model/`                              | `resource.queries.ts`、`useResourceList`   |
| 纯格式化、排序、过滤             | `*.utils.ts` 或 `lib/`                          | `formatDate`、`sortByName`                 |

## 案例 1：页面列表拆分

初始问题：

```tsx
export function ResourceListPage() {
  return (
    <main>
      <header>...</header>
      <section>
        <input />
        <button>Search</button>
      </section>
      <ul>
        {resources.map((resource) => (
          <li key={resource.id}>
            <h2>{resource.name}</h2>
            <p>{resource.description}</p>
            <button>Edit</button>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

推荐拆法：

```text
pages/resource-list/
  ResourceListPage.tsx
  ResourceListPage.module.css
  ui/
    ResourceFilterBar/
      ResourceFilterBar.tsx
      ResourceFilterBar.module.css
      index.ts
    ResourceListItem/
      ResourceListItem.tsx
      ResourceListItem.module.css
      index.ts
```

判断：

- `ResourceFilterBar` 有明确交互边界，适合独立管理输入、提交和 disabled 状态。
- `ResourceListItem` 是重复 UI 单元，适合独立处理可访问结构和 item actions。
- `ResourceListPage` 保留 route-level composition，不承载列表项细节。

## 案例 2：表格区域拆分

推荐边界：

```text
pages/resource-table/
  ResourceTablePage.tsx
  ui/
    ResourceTableToolbar/
    ResourceTableView/
    ResourceTableEmptyState/
    ResourceTableRow/
```

拆分规则：

- toolbar 有筛选、搜索、批量操作时独立。
- table header 如果只是静态 `Name`、`Status`，可以留在 `ResourceTableView`。
- table header 出现排序、列宽、列显隐、批量选择时，拆成 `ResourceTableHeader`。
- row 有 hover action、keyboard navigation、selection、context menu 时，拆成 `ResourceTableRow`。
- empty state 有 action、permission 或引导差异时，拆成 `ResourceTableEmptyState`。

## 案例 3：弹窗和表单拆分

推荐结构：

```text
features/invite-user/
  model/
    useInviteUserForm.ts
  ui/
    InviteUserDialog/
      InviteUserDialog.tsx
      InviteUserDialog.module.css
      index.ts
    InviteUserForm/
      InviteUserForm.tsx
      InviteUserForm.module.css
      index.ts
```

判断：

- `InviteUserDialog` 负责 open state、标题、关闭、提交按钮区域和 dialog 可访问性边界。
- `InviteUserForm` 负责字段布局、校验提示和表单控件状态。
- 表单提交、mutation、错误映射放 `model/`，不要散落在 UI JSX 内。
- 如果 `InviteUserForm` 永远只在这个 dialog 中使用，保留在 feature 内，不进入 shared。

## 案例 4：业务组件不要提升到 shared

反例：

```text
src/shared/ui/UserPermissionSelect/
```

问题：

- `UserPermissionSelect` 知道 `owner`、`editor`、`viewer` 等业务角色。
- 角色来自 workspace permission model，不是无业务基础 UI。
- shared UI 一旦依赖业务枚举，会被其他模块错误复用。

推荐：

```text
entities/user-permission/ui/UserPermissionSelect/
shared/ui/Select/
```

判断：

- `shared/ui/Select` 只负责基础选择器交互、状态和可访问性。
- `UserPermissionSelect` 负责把业务角色映射成 select options。

## 案例 5：拆 hook 而不是拆组件

适合拆 hook：

```tsx
function StatusBar() {
  const isOnline = useOnlineStatus();
  return <p>{isOnline ? 'Online' : 'Disconnected'}</p>;
}
```

推荐放置：

```text
shared/hooks/useOnlineStatus.ts
```

判断：

- 复用的是订阅网络状态的 stateful logic，不是 UI。
- 每个调用方要自己决定如何展示 `Online`、`Disconnected`、button disabled 或 toast。
- 如果 hook 只服务某个 feature，放 `features/<feature-name>/model/`，不要提前进 shared。

不建议：

```tsx
function useMount(fn: () => void) {
  useEffect(() => {
    fn();
  }, []);
}
```

原因：

- 这种 lifecycle wrapper 没有具体业务意图。
- 容易隐藏依赖关系，让 Effect 不随输入变化。
- 更好的做法是按真实目的命名，例如 `useChatRoom(options)`、`useImpressionLog(eventName, data)`。

## 案例 6：拆 utility 而不是拆 hook

反例：

```ts
function useSortedResources(resources: Resource[]) {
  return resources.slice().sort((a, b) => a.name.localeCompare(b.name));
}
```

推荐：

```ts
function sortResourcesByName(resources: Resource[]) {
  return resources.slice().sort((a, b) => a.name.localeCompare(b.name));
}
```

判断：

- 没有使用 React state、Effect、context 或其他 hook。
- 这是纯计算函数，不应该使用 `use` 前缀。
- 放置位置按作用域决定：页面私有放页面附近，跨模块复用再进 `shared/utils/`。

## 案例 7：避免 prop tunneling 式拆分

反例：

```tsx
function ResourcePanel(props: ResourcePanelProps) {
  return <ResourcePanelBody {...props} />;
}

function ResourcePanelBody(props: ResourcePanelProps) {
  return <ResourceActions {...props} />;
}
```

问题：

- 中间组件没有独立职责，只是在转发 props。
- 抽分增加了跳转成本，没有降低复杂度。
- 如果 props 数量越来越多，说明 state owner 或组合边界可能错了。

推荐：

- 删除无意义中间层。
- 让 `ResourcePanel` 直接组合有语义的子组件。
- 或把重复的交互逻辑抽到 hook，把真正的 UI 边界保留为组件。

## 案例 8：从 page-private 升级到 shared

阶段 1：页面私有。

```text
pages/project-list/ui/ProjectCard/
```

阶段 2：第二个页面出现相同行为，但业务仍是 `Project`。

```text
entities/project/ui/ProjectCard/
```

阶段 3：多个领域都需要同类无业务卡片布局。

```text
shared/ui/Card/
entities/project/ui/ProjectCard/
entities/team/ui/TeamCard/
```

判断：

- 先上移到 entity，不直接进 shared。
- 只有当组件可以去掉业务名、业务字段和业务状态后，才抽成 shared UI。
- shared UI 暴露的是通用外观、状态和交互；业务组件负责传入内容和业务动作。

## 案例 9：dashboard 页面拆分

初始问题：

- 一个 dashboard page 同时包含 summary cards、趋势图、活动列表、筛选器和异常提醒。
- 所有 JSX、数据整理和空态都堆在 `DashboardPage.tsx`。

推荐结构：

```text
pages/dashboard/
  DashboardPage.tsx
  model/
    useDashboardData.ts
  ui/
    DashboardSummary/
      DashboardSummary.tsx
      DashboardSummary.module.css
      index.ts
    DashboardTrendPanel/
      DashboardTrendPanel.tsx
      DashboardTrendPanel.module.css
      index.ts
    DashboardActivityList/
      DashboardActivityList.tsx
      DashboardActivityList.module.css
      index.ts
```

判断：

- `DashboardPage` 负责 route-level composition、读取 query hook 和组织页面状态。
- `DashboardSummary`、`DashboardTrendPanel`、`DashboardActivityList` 负责独立 UI 区块。
- 如果 summary card 是完全通用的数字展示，且多个页面复用，再抽 `shared/ui/MetricCard`。
- 如果 trend chart 绑定业务指标、权限或接口字段，保留在 page 或 feature 内，不直接进 shared。

## 案例 10：tabs 和 steps 拆分

反例：

```text
shared/ui/ProjectSettingsTabs/
```

问题：

- `ProjectSettingsTabs` 知道 `general`、`members`、`billing` 等业务 tab。
- shared UI 被业务路由和权限污染。

推荐：

```text
shared/ui/Tabs/
pages/project-settings/ui/ProjectSettingsTabs/
features/onboarding/ui/OnboardingSteps/
```

判断：

- `shared/ui/Tabs` 只负责 tablist、tab、tabpanel、keyboard navigation、selected state。
- `ProjectSettingsTabs` 负责业务 tab 配置、权限过滤和 route 映射。
- `OnboardingSteps` 负责业务步骤、完成状态和下一步动作。
- 如果只是页面内两个静态 tab，且没有复用或复杂状态，可以先留在 page 组件内。

## 案例 11：详情页拆分

推荐结构：

```text
pages/resource-detail/
  ResourceDetailPage.tsx
  model/
    useResourceDetail.ts
  ui/
    ResourceDetailHeader/
    ResourceDetailProperties/
    ResourceDetailActivity/
    ResourceDetailDangerZone/
```

拆分规则：

- header 有标题、状态、主操作、更多菜单时独立。
- properties 如果只是 3 个静态字段，可以留在页面内；字段很多、存在编辑态或权限控制时独立。
- activity 有分页、loading、empty、retry 时独立。
- danger zone 有破坏性操作和确认流程时独立到 feature，例如 `features/delete-resource/ui/DeleteResourceDialog/`。
- 详情页的 query hook 留在 page model；业务动作 mutation 进入对应 feature model。

## 案例 12：复杂表单字段组拆分

初始问题：

- 一个 form 同时包含基础信息、权限、通知、账单、危险操作。
- 每个字段都在一个 `Form.tsx` 中管理。

推荐结构：

```text
features/update-resource/
  model/
    useResourceForm.ts
  ui/
    ResourceForm/
    ResourceBasicFields/
    ResourcePermissionFields/
    ResourceNotificationFields/
```

判断：

- 字段组有独立标题、校验、disabled 条件或错误提示时，可以拆成 field group。
- 单个 `TextField`、`SelectField` 如果完全通用，可以复用 `shared/ui` primitive。
- 字段组知道业务字段和校验规则，保留在 feature 或 entity，不进 shared。
- form state owner 保持清晰：父 form 管理提交和跨字段校验，field group 管理局部展示。

不建议：

- 每个字段都拆成一个业务组件，导致父组件只剩几十个 props 透传。
- 把业务校验规则塞进 `shared/ui/Input`。

## 案例 13：菜单、popover 和 command palette

推荐结构：

```text
shared/ui/DropdownMenu/
shared/ui/Popover/
features/resource-actions/ui/ResourceActionMenu/
features/command-palette/ui/CommandPalette/
```

判断：

- `shared/ui/DropdownMenu` 负责基础 overlay、focus trap、keyboard navigation 和 menu item 状态。
- `ResourceActionMenu` 负责业务 action、权限过滤、危险操作确认入口。
- `CommandPalette` 通常是 feature：它知道命令来源、搜索、权限和执行动作。
- 如果 popover 内容只有当前页面使用，放 `pages/<page-name>/ui/ContentPopover/`。

反例：

```text
shared/ui/DeleteMenuItem/
```

问题：

- delete 行为需要业务确认、权限、mutation、toast 和缓存刷新，不是基础 UI。

## 案例 14：虚拟列表和无限滚动

推荐结构：

```text
pages/resource-list/
  model/
    useResourceInfiniteList.ts
  ui/
    ResourceVirtualList/
    ResourceListItem/
    ResourceListLoadingRow/
    ResourceListEndMarker/
```

判断：

- 虚拟滚动容器有测量、overscan、scroll restore、loading sentinel 时独立。
- item renderer 有 hover、selection、keyboard 或 context menu 时独立。
- 数据分页和 cursor 逻辑放 model，不放在 item 组件。
- 如果虚拟列表能力完全通用，且能通过 render prop 或 children 表达，再考虑 `shared/ui/VirtualList`。
- 如果性能库或浏览器 API 使用复杂，组件目录内可补 `useVirtualListMeasurements.ts`。

## 案例 15：loading、empty、error 状态视图

推荐结构：

```text
shared/ui/EmptyState/
shared/ui/ErrorState/
pages/resource-list/ui/ResourceListEmptyState/
pages/resource-list/ui/ResourceListErrorState/
```

判断：

- `shared/ui/EmptyState` 只负责通用布局、图标、标题、描述、action slot。
- `ResourceListEmptyState` 负责业务文案、权限提示、创建入口和筛选条件解释。
- error state 如果只展示通用 retry，可以用 shared；如果要解释业务原因，放页面或 feature。
- loading skeleton 如果绑定具体布局，放在对应 UI 模块；通用 spinner 才进 shared。

反例：

```text
shared/ui/NoPermissionToCreateResourceEmptyState/
```

问题：

- 业务权限和资源类型进入 shared，后续会污染其他模块。

## 案例 16：布局组件和业务区块

推荐拆法：

```text
shared/ui/PageLayout/
shared/ui/SplitPane/
widgets/AppSidebar/
widgets/WorkspaceTopbar/
pages/settings/ui/SettingsLayout/
```

判断：

- `PageLayout`、`SplitPane` 这种只处理布局、spacing、slot 的组件可以进 shared。
- `WorkspaceTopbar`、`AppSidebar` 知道 workspace、navigation、user menu，属于 widget。
- `SettingsLayout` 如果绑定 settings routes 和 tabs，放 page-private 或 widget，不进 shared。
- 布局组件不要读取业务 query，也不要知道 route-specific action。

## 案例 17：权限、角色和可见性控制

反例：

```tsx
function Button({ requiredPermission, resourceId }: ButtonProps) {
  const canClick = usePermission(resourceId, requiredPermission);
  return <button disabled={!canClick} />;
}
```

问题：

- `shared/ui/Button` 被权限模型污染。
- 基础按钮不应该知道 resource、role、permission。

推荐：

```text
shared/ui/Button/
features/resource-permission/ui/ResourcePermissionGate/
features/delete-resource/ui/DeleteResourceButton/
```

判断：

- permission query 和判断放 feature/model 或 entity/model。
- shared button 只接收 `disabled`、`aria-disabled`、`variant`、`onClick`。
- `ResourcePermissionGate` 可以负责按权限显示、隐藏或禁用业务操作。

## 案例 18：i18n 和文案边界

推荐：

```text
shared/ui/ConfirmDialog/
features/delete-resource/ui/DeleteResourceDialog/
```

判断：

- `ConfirmDialog` 提供 `title`、`description`、`confirmLabel`、`cancelLabel` slots 或 props。
- `DeleteResourceDialog` 负责具体文案、资源名称、风险提示和提交动作。
- shared UI 不硬编码业务文案，也不直接读取特定 namespace 的 translation key。
- 页面私有文案和 route-specific empty state 留在页面或 feature 内。

## 案例 19：数据容器和展示组件分离

适用场景：

- 一个 UI 区块需要 query、mutation、cache invalidation、toast、权限和 loading/error 状态。

推荐结构：

```text
features/update-resource/
  model/
    useUpdateResource.ts
  ui/
    UpdateResourcePanel/
      UpdateResourcePanel.tsx
      UpdateResourcePanel.module.css
      index.ts
```

拆分方式：

- `useUpdateResource` 管理 mutation、错误映射和 side effects。
- `UpdateResourcePanel` 接收清晰 props 和 callbacks，负责展示和交互。
- 如果需要容器组件，可以命名为 `UpdateResourcePanelContainer` 并放在 feature 内，不放 shared。

不建议：

- 在 shared UI 内部直接调用 mutation。
- 让展示组件自己决定 query key、cache invalidation 或 toast 文案。

## 案例 20：第三方库 adapter

推荐结构：

```text
shared/ui/DatePicker/
shared/ui/RichTextEditor/
features/resource-description/ui/ResourceDescriptionEditor/
```

判断：

- 第三方 UI 库不要散落在业务代码里直接使用；先用 shared adapter 收敛基础 API、样式和可访问性。
- adapter 不知道业务字段，只暴露稳定 props。
- 业务 wrapper 负责把 domain value、validation、permission 和 submit action 映射到 adapter。
- 如果第三方库只在一个 feature 使用，adapter 可以先放在 feature 内，等第二个稳定场景出现再上移。

## PR 检查清单

- 新组件是否有稳定、具体、可搜索的名称。
- 是否放在正确层级，而不是默认塞进 `shared/ui`。
- 是否使用 `ComponentName/ComponentName.tsx` 目录结构。
- 父组件是否仍保留 route-level composition，而不是堆 UI 细节。
- 子组件是否没有直接依赖 API DTO、request client 或不该知道的 route context。
- hook 是否只用于 stateful logic，纯函数是否没有 `use` 前缀。
- shared UI 是否无业务语义，并支持 `className`、状态和可访问性边界。
- 业务文案、权限、角色、query key、mutation 和 toast 是否留在 page、feature 或 entity 层。
- 第三方 UI 库是否通过 adapter 收敛，而不是散落在业务组件中。
- loading、empty、error 是否按布局和业务语义放到正确层级。
- app shell、providers、router、route page entry 是否没有写入 component inventory。
