# Accessibility And UI States

UI 状态、交互反馈和可访问性硬规则。

## 状态规则

| 状态        | 必须满足                               |
| ----------- | -------------------------------------- |
| `loading`   | 避免布局剧烈跳动。                     |
| `empty`     | 说明当前为空，并按场景给下一步操作。   |
| `error`     | 显示用户可理解反馈，不只写 console。   |
| `disabled`  | 同时阻止交互并表达不可用原因。         |
| `readonly`  | 内容保持可见，只限制编辑。             |
| `pending`   | 防重复提交，并保留清晰文案或进度提示。 |
| `success`   | 对用户任务结果给可见反馈。             |
| `no access` | 不显示误导性可执行入口。               |

- 异步提交失败后应恢复可操作状态，并保留用户已输入内容。
- 状态变化影响任务结果时，必要时使用合适的 live region。
- loading/pending 图标不能是唯一表达，必要时配合 `aria-busy`、可见文本或状态区域。

## 交互控件

- 可点击元素优先使用 `button`、`a` 或原生控件。
- 表单外普通按钮显式设置 `type="button"`；提交按钮用 `type="submit"`，并在 form `onSubmit` 统一防重复。
- 真正不可操作的控件优先用原生 `disabled`。
- 使用 `aria-disabled` 时，handler 中仍必须阻止动作。
- 图标按钮必须有可访问名称，例如 `aria-label`。
- 颜色不能作为唯一状态表达；focus 样式不能移除，除非有等价替代。

## 表单和浮层

- 表单字段应有 label、description 或 error message。
- 表单错误使用可见文案，并按场景用 `aria-invalid`、`aria-describedby` 关联。
- dialog 必须有 title，必要时有 description。
- menu、popover、select、tooltip 优先复用 shared UI，避免重复实现键盘交互。
- overlay 打开时应有明确焦点入口；关闭后焦点回到合理触发点。

## ARIA 和键盘

- 优先使用原生 HTML 语义；原生语义无法表达时才添加 role 或 ARIA。
- 使用自定义 role 时，必须实现对应键盘、焦点和状态行为。
- 键盘用户必须能完成主要路径，不能出现无法进入或无法退出的 focus trap。
- 动画和过渡不应阻断交互；明显动态效果应尊重 `prefers-reduced-motion`。

## 响应式和文本

- 文本不能溢出按钮、卡片、表格单元或浮层容器。
- 固定格式组件需要稳定尺寸或响应式约束。
- 移动端检查换行和触控面积；图标按钮不能只依赖视觉图标尺寸。
- 不使用 viewport width 直接缩放字体。
