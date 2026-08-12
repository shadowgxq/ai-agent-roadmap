"""直接运行一次 Lighthouse 摘要，便于不经过 MCP host 调试核心逻辑。"""

from __future__ import annotations

import argparse
import asyncio
import sys

from lighthouse_runner import LighthouseError, run_lighthouse, summarize_report


async def _run(url: str, max_issues: int) -> int:
    try:
        raw_report = await run_lighthouse(url)
        report = summarize_report(
            raw_report,
            requested_url=url.strip(),
            max_issues=max_issues,
        )
    except LighthouseError as exc:
        print(f"审计失败：{exc}", file=sys.stderr)
        return 1

    print(report.model_dump_json(indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一次 Lighthouse 页面审计")
    parser.add_argument("url", help="要审计的 http(s) URL")
    parser.add_argument(
        "--max-issues",
        type=int,
        default=8,
        help="最多返回多少条失败 audit（1-10，默认 8）",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.url, args.max_issues))


if __name__ == "__main__":
    raise SystemExit(main())
