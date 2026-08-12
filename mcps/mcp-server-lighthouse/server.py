"""面向 MCP host 的 Lighthouse 网页审计 server。"""

from mcp.server.mcpserver import MCPServer

from lighthouse_runner import (
    LighthouseError,
    LighthouseReport,
    run_lighthouse,
    summarize_report,
)


mcp = MCPServer("mcp-server-lighthouse")


@mcp.tool()
async def audit_page(url: str, max_issues: int = 8) -> LighthouseReport:
    """Audit an HTTP(S) page for performance, accessibility, SEO, and best practices.

    Use this tool for a page-level web audit. Do not use it for source-code-only
    review or pages that require an authenticated session. The result is a
    compact summary with category scores, core metrics, and the most important
    failing audits.
    """

    try:
        raw_report = await run_lighthouse(url)
        return summarize_report(
            raw_report,
            requested_url=url.strip(),
            max_issues=max_issues,
        )
    except LighthouseError as exc:
        # MCP SDK 会把工具函数异常包装成 isError=true 的 tool result；
        # 这里保留可读错误，同时让 stdio server 继续存活处理后续请求。
        raise RuntimeError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run()
