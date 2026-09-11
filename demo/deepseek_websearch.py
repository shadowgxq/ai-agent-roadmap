#!/usr/bin/env python3
"""DeepSeek 原生 Web Search 的最小示例。

运行：
    python demo/deepseek_websearch.py "搜索今天 AI 行业的重要新闻"

脚本会读取项目中的 agent-mini/.env，并使用其中的 CODEX_API_KEY。
本示例使用 Python 标准库直接请求 DeepSeek Anthropic 兼容接口，
以便拿到结构化的 server_tool_use 和 web_search_tool_result。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL = "deepseek-flash"
LOGGER = logging.getLogger("deepseek_websearch")
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

WEBSEARCH_INSTRUCTIONS = """
你是一个严谨的中文搜索助手。

当用户的问题涉及最新、实时或可能变化的信息时，必须先调用 web_search，再回答。
回答要求：
1. 只使用搜索结果中有依据的信息，不要编造事实。
2. 优先使用官方、权威或一手来源。
3. 用简洁的中文总结关键结论，并注明具体日期。
4. 在相关结论后附上来源链接；如果来源不足或互相矛盾，要明确说明。
""".strip()


def load_project_env_value(name: str) -> str | None:
    """从项目根目录或 agent-mini/.env 读取指定配置，不覆盖当前进程环境。"""
    for env_file in (PROJECT_ROOT / ".env", PROJECT_ROOT / "agent-mini" / ".env"):
        if not env_file.is_file():
            continue

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()

            key, value = line.split("=", 1)
            if key.strip() != name:
                continue

            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None

    return None


def dump_json(value: object) -> str:
    """格式化 JSON，便于观察原始请求和响应结构。"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def log_response_structure(response: dict[str, object]) -> None:
    """记录 Web Search 调用和响应 block 结构，不打印加密搜索内容。"""
    content = response.get("content") or []
    LOGGER.info(
        "响应结构: model=%s, stop_reason=%s, content_blocks=%d",
        response.get("model", "unknown"),
        response.get("stop_reason", "unknown"),
        len(content),
    )

    web_search_call_count = 0
    for index, block in enumerate(content):
        if not isinstance(block, dict):
            LOGGER.info("content[%d]: 非对象，type=%s",
                        index, type(block).__name__)
            continue

        block_type = block.get("type", "unknown")
        if block_type == "server_tool_use" and block.get("name") == "web_search":
            web_search_call_count += 1
            LOGGER.info(
                "web_search server_tool_use[%d] 结构:\n%s",
                index,
                dump_json(
                    {
                        "type": block.get("type"),
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input"),
                        "caller": block.get("caller"),
                    }
                ),
            )
            continue

        if block_type == "web_search_tool_result":
            result_summary = []
            for result in block.get("content") or []:
                if not isinstance(result, dict):
                    continue
                if result.get("type") == "web_search_result":
                    result_summary.append(
                        {
                            "type": result.get("type"),
                            "title": result.get("title"),
                            "url": result.get("url"),
                            "page_age": result.get("page_age"),
                        }
                    )
                else:
                    result_summary.append(result)
            LOGGER.info(
                "web_search_tool_result[%d] 结构:\n%s",
                index,
                dump_json(
                    {
                        "type": block.get("type"),
                        "tool_use_id": block.get("tool_use_id"),
                        "content": result_summary,
                    }
                ),
            )
            continue

        if block_type == "thinking":
            LOGGER.info("content[%d]: type=thinking（内容不打印）", index)
        else:
            LOGGER.info("content[%d]: type=%s", index, block_type)

    if web_search_call_count == 0:
        LOGGER.warning(
            "本次响应没有 server_tool_use(web_search)：API Key 可用，"
            "但当前请求未实际执行 Web Search。"
        )


def extract_output_text(response: dict[str, object]) -> str:
    """从 Anthropic Messages API 原始 JSON 中提取最终回答文本。"""
    texts: list[str] = []
    for block in response.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        if isinstance(block.get("text"), str):
            texts.append(block["text"])
    return "\n".join(texts)


def main() -> None:
    api_key = load_project_env_value("CODEX_API_KEY")
    if not api_key:
        raise SystemExit("项目中未找到 agent-mini/.env 的 CODEX_API_KEY")

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = "搜索下今天杭州的天气"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    payload = {
        "model": MODEL,
        "max_tokens": 1500,
        "system": WEBSEARCH_INSTRUCTIONS,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}],
            }
        ],
        "tools": [WEB_SEARCH_TOOL],
        # 强制本次请求使用 Web Search server tool。
        "tool_choice": {"type": "tool", "name": "web_search"},
    }
    LOGGER.info("请求结构:\n%s", dump_json(payload))

    request = Request(
        "https://api.deepseek.com/anthropic/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as result:
            response = json.load(result)
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        LOGGER.error("DeepSeek API 返回 HTTP %s:\n%s", error.code, error_body)
        raise SystemExit(1) from error
    except URLError as error:
        LOGGER.error("无法连接 DeepSeek API: %s", error.reason)
        raise SystemExit(1) from error

    log_response_structure(response)
    print("\n--- answer ---")
    print(extract_output_text(response))


if __name__ == "__main__":
    main()
