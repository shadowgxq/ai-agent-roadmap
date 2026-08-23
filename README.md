# AI Agent Roadmap｜W12 Coding Agent Demo

W12 把 W11 的 Agent Web 接到受控代码运行时：浏览器只消费 FastAPI/SSE 事件，Agent Runtime 通过 `Workspace` 读写代码，通过 `Executor` 执行命令；Demo 默认使用 Docker Sandbox 和一次性的 Git Worktree。

## 架构

```text
Browser
  │  Vite /api proxy + EventSource
  ▼
FastAPI Web Adapter
  │  Session / Run Manager
  ▼
Agent Runtime
  ├─ Repository → detached RepositoryWorkspace
  ├─ File/Search Tools → Workspace boundary
  └─ run_shell → DockerExecutor
                    │ --network none / resource limits / non-root
                    ▼
                 Docker Sandbox
                    │ bind mount
                    ▼
              temporary Git Worktree
                    │ structured events
                    ▼
              SSE → React Timeline / DiffView
```

`RepositoryWorkspace` 默认从当前 `HEAD` 创建临时 worktree。Run 结束后 worktree 会被清理，用户仍可在实时事件和 Session History 中查看文本、Tool Call、Tool Result、Task Status 和 Diff；W12 暂不实现把 Diff 自动应用回主分支或创建 Pull Request。

## 本地运行

需要 Python 3.12、[uv](https://docs.astral.sh/uv/)、Node 20.19+、pnpm 和 Docker。

1. 准备 Agent 配置（只填写本机环境变量，不要把密钥提交到 Git）：

   ```bash
   cd agent-mini
   uv sync
   cp -n .env.example .env
   # 编辑 .env，至少填写 CODEX_API_KEY；按实际 Provider 调整 CODEX_BASE_URL/CODEX_MODEL
   ```

2. 构建 Sandbox 镜像：

   ```bash
   make sandbox-build
   ```

3. 启动 FastAPI + SSE（保持这个终端运行）：

   ```bash
   make web
   ```

   默认监听 `http://127.0.0.1:3000`，工作区是本仓库根目录；每个 Run 使用 Docker Sandbox 和 detached Git Worktree。

4. 新开终端启动前端：

   ```bash
   cd frontend
   pnpm install
   cp -n .env.example .env
   pnpm dev
   ```

   打开 <http://localhost:5173/agent>。前端开发服务器会把 `/api` 代理到 `http://localhost:3000`。

### 常用运行参数

```bash
# 使用本地 Executor 调试，不经过 Docker
make web EXECUTOR_BACKEND=local

# 指定另一个 Git 仓库作为 Agent 工作区
make web WEB_WORKDIR=/absolute/path/to/repository

# 指定 Sandbox 镜像名
make sandbox-build SANDBOX_IMAGE=my-agent-sandbox:dev
make web SANDBOX_IMAGE=my-agent-sandbox:dev
```

## Demo 任务

在页面输入以下类型的任务即可观察完整链路：

1. 阅读仓库并解释：`请阅读 agent-mini/src/web/runs.py，解释 Run 从创建到 SSE 结束的生命周期。`
2. 修复并验证：`请检查 agent-mini/evals/buggy_project 中的一个失败测试，提出最小修复并运行对应测试。`
3. 修改并查看 Diff：`请给 agent-mini/src/web/models.py 的 Run 增加一个清晰的字段说明，并展示修改 Diff。`

危险命令会进入 `waiting_confirmation`，页面会显示命令和原因；允许、拒绝或取消都通过 Run API 收束为明确状态。运行期间重复提交会返回 409，页面会切换到已有 Run 并提供重连/取消入口。

## 边界与限制

- 默认是本地 Demo，不代表已经部署到公网，也不包含真实账号、生产数据库、队列或多实例协调。
- Docker Sandbox 只挂载当前临时 Worktree，使用 `--network none`、资源限制和非 root 用户；运行时不会把宿主环境变量传入容器。
- Sandbox 镜像只提供 Python、Git 和基础 Shell。目标仓库的额外测试/构建依赖需要由镜像或仓库提前准备，W12 不自动联网安装依赖。
- 本地验证使用 fake runner 和单元测试，不自动调用真实 LLM；真实 Demo 运行会消耗 Provider 配额，并应由用户主动发起。

## 代码入口

| 入口 | 职责 |
| --- | --- |
| `agent-mini/src/execution/workspace.py` | Workspace 路径边界与结构化 Diff |
| `agent-mini/src/execution/repository.py` | Git 临时 Worktree 生命周期 |
| `agent-mini/src/execution/executor.py` | Local/Docker 命令执行与策略确认 |
| `agent-mini/src/web/runs.py` | Session、Run、SSE、确认、取消状态机 |
| `agent-mini/src/web/app.py` | FastAPI 路由与 Demo 配置 |
| `frontend/src/pages/agent/` | 状态 Hook、事件时间线、Tool/Diff/History UI |
