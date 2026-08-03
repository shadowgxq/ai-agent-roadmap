# AI Docs

`docs/ai/` 保存 AI 前端端到端交付规范和 Manager/OpenSpec 流程，不保存 Agent 协作硬规则、前端编码细则、业务需求、接口契约或当前执行状态。

## 文件

- `ai-frontend-delivery-best-practice.md`：从产品、UX、视觉和接口输入，到 Manager/OpenSpec、前端垂直切片、验证与归档的端到端交付规范。涉及事实源划分、阶段 Gate 或完整前端交付路径时读取。
- `openspec-manager-flow.md`：Manager/OpenSpec 生命周期、`manager/plan.yaml` 状态模型、batch/wave、执行入口映射、拆分粒度概览、Goal 连续推进和 Ralph shell runner。涉及 PRD 拆分、批次执行、自动循环或归档时读取。subagent handoff 格式由 `$manager-execute-current-batch` skill 自身维护，本目录不重复。

## 维护规则

- 全局文档地图和读取顺序以 `docs/README.md` 为准。
- Agent 协作硬规则、验证范围和交付要求写入根目录 `AGENTS.md`，不要复制到本目录。
- 端到端交付原则写入 `ai-frontend-delivery-best-practice.md`；Manager/OpenSpec 的状态机和执行细节只写入 `openspec-manager-flow.md`。
- 前端工程规范写入 `docs/frontend/`，不要复制到本目录。
- 当前执行状态写入 `manager/plan.yaml`，不要写入本目录。
- 新增 AI 文档前，优先判断能否并入现有文件；只有形成稳定独立主题时再新增文件。
