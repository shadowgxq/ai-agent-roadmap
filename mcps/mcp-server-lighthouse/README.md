# mcp-server-lighthouse

一个把 Lighthouse 网页性能审计接入 MCP 的轻量 server。它把 Lighthouse
原始 JSON 压缩成模型更容易使用的摘要：分类分数、核心指标和有限数量的高优先级问题。

## 能做什么

| 工具 | 用途 |
| --- | --- |
| `audit_page` | 审计一个 HTTP(S) 页面，返回性能、可访问性、最佳实践和 SEO 摘要 |
| `compare_pages` | 顺序审计两个页面，返回两个摘要以及 `second - first` 的分类分数差值 |

`compare_pages` 适合比较 staging 与 production，或比较优化前后的页面。分数差值为正表示第二个页面更好。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- Chrome 或 Chromium

安装 Python 和 Lighthouse 依赖：

```bash
uv sync
npm install
```

安装完成后，MCP server 的命令入口是 `mcp-server-lighthouse`。

WSL 中使用 Chromium 时，在项目目录创建被 Git 忽略的 `.env`：

```dotenv
CHROME_PATH=/snap/bin/chromium
LIGHTHOUSE_NO_SANDBOX=true
```

如果 Chrome 位于其他路径，修改 `CHROME_PATH` 即可。`CHROME_PATH` 必须和运行 Lighthouse 的 Node.js 处于同一平台。

## 直接运行 CLI

不经过 MCP host 时，可以直接检查底层审计：

```bash
uv run lighthouse-audit http://localhost:5174/ --max-issues 3
```

输出是精简后的 JSON，而不是完整 Lighthouse 报告。页面必须能从运行 server 的环境访问。

## 配置 Claude Code

如果 Claude Code 在 WSL 中运行，可以在项目目录执行：

```bash
claude mcp add --transport stdio lighthouse -- \
  uv --directory /home/gxq/ai-agent-roadmap/mcps/mcp-server-lighthouse \
  run mcp-server-lighthouse
```

如果需要显式指定 Chromium，可把环境变量加到命令前：

```bash
CHROME_PATH=/snap/bin/chromium claude mcp add --transport stdio lighthouse -- \
  uv --directory /home/gxq/ai-agent-roadmap/mcps/mcp-server-lighthouse \
  run mcp-server-lighthouse
```

添加后，在 Claude Code 中查看 MCP 工具列表，应该能看到 `audit_page` 和 `compare_pages`。

## 配置 Claude Desktop

在 Claude Desktop 的 MCP 配置中加入以下 JSON。Windows 主机通过 `wsl.exe` 启动 WSL 内的 server：

```json
{
  "mcpServers": {
    "lighthouse": {
      "command": "wsl.exe",
      "args": [
        "-d",
        "Ubuntu-22.04",
        "--cd",
        "/home/gxq/ai-agent-roadmap/mcps/mcp-server-lighthouse",
        "--",
        "uv",
        "run",
        "mcp-server-lighthouse"
      ]
    }
  }
}
```

server 会自动加载项目目录下的 `.env`；因此不要把真实路径以外的密钥或个人配置提交到 Git。

## 工具输出

`audit_page` 的结果包含：

- `scores`：各 Lighthouse category 的 0–100 分数
- `metrics`：FCP、LCP、TBT、CLS、Speed Index 等核心指标
- `issues`：按分数排序的有限数量失败 audit，以及修复建议

`compare_pages` 额外包含：

- `first`：第一个 URL 的摘要
- `second`：第二个 URL 的摘要
- `score_deltas`：各共同 category 的 `second - first` 分差

工具不会直接返回几万字符的原始 Lighthouse JSON，避免把底层报告直接撑满模型上下文。

## stdio 约定

这是一个 stdio MCP server。stdout 只用于 MCP 协议消息；不要在 server 中向 stdout 打印调试日志，否则会破坏 JSON-RPC 通道。错误会转换成可读的 MCP tool error，server 进程仍可继续处理后续请求。
