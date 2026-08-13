"""面向 MCP host 的 Lighthouse 网页审计 server。"""

from mcp.server.mcpserver import MCPServer

from lighthouse_runner import (
    LighthouseComparison,
    LighthouseError,
    LighthouseReport,
    compare_reports,
    run_lighthouse,
    summarize_report,
)


mcp = MCPServer("mcp-server-lighthouse")


async def _audit_page(url: str, max_issues: int) -> LighthouseReport:
    """执行一次审计并统一转换为面向模型的摘要。"""

    raw_report = await run_lighthouse(url)
    return summarize_report(
        raw_report,
        requested_url=url.strip(),
        max_issues=max_issues,
    )


@mcp.tool()
async def audit_page(url: str, max_issues: int = 8) -> LighthouseReport:
    """Audit an HTTP(S) page for performance, accessibility, SEO, and best practices.

    Use this tool for a page-level web audit. Do not use it for source-code-only
    review or pages that require an authenticated session. The result is a
    compact summary with category scores, core metrics, and the most important
    failing audits.
    """

    try:
        return await _audit_page(url, max_issues)
    except LighthouseError as exc:
        # MCP SDK 会把工具函数异常包装成 isError=true 的 tool result；
        # 这里保留可读错误，同时让 stdio server 继续存活处理后续请求。
        raise RuntimeError(str(exc)) from exc


@mcp.tool()
async def compare_pages(
    first_url: str,
    second_url: str,
    max_issues: int = 3,
) -> LighthouseComparison:
    """Compare two reachable HTTP(S) pages and return score deltas.

    Use this tool when the user wants to compare two URLs, such as a staging
    page and its production counterpart. The score delta is ``second - first``;
    positive values mean the second page scored better. Each nested report is
    compact and includes category scores, core metrics, and top failing audits.
    """

    try:
        # 顺序执行两个 Lighthouse，避免在资源有限的开发机上同时启动
        # 两个 Chrome 实例导致审计互相抢占端口或内存。
        first = await _audit_page(first_url, max_issues)
        second = await _audit_page(second_url, max_issues)
        return compare_reports(first, second)
    except LighthouseError as exc:
        raise RuntimeError(str(exc)) from exc


def main() -> None:
    """启动 stdio MCP server，供 CLI entry point 和直接运行共用。"""

    mcp.run()


if __name__ == "__main__":
    main()
