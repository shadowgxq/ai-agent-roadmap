#!/usr/bin/env python3
"""OpenAI Responses Web Search probe (standard library only).

Run from the project root:
    python3 demo/codex_websearch.py "Search the latest OpenAI news and cite sources"
Offline checks (no .env reads or API requests):
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s demo -p 'test_codex_websearch.py' -v

Configure CODEX_API_KEY, CODEX_BASE_URL (API prefix, e.g. https://example.org/v1),
and CODEX_MODEL for a provider/model supporting Responses and web_search.
Process environment variables take precedence over root .env, then agent-mini/.env.
The gateway and model have no defaults. Example (keep credentials in local env):
    CODEX_BASE_URL=https://example.org/v1 CODEX_MODEL=your-search-model \
        python3 demo/codex_websearch.py "Search and cite sources"
One HTTP request; no retry or fallback.
The 120s timeout is a socket-operation timeout, not a total deadline.
The provider may perform multiple searches internally: there is no tool-call cap.
Search evidence is checked in returned JSON; source accuracy is not verified.
Docs: https://developers.openai.com/api/docs/guides/tools-web-search
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from deepseek_websearch import WEBSEARCH_INSTRUCTIONS, load_project_env_value

TIMEOUT_SECONDS = 120
MAX_OUTPUT_TOKENS = 1500
PRINT_LIMIT = 8000
LOGGER = logging.getLogger("codex_websearch")


def load_config() -> tuple[str, str, str]:
    values = []
    for name in ("CODEX_API_KEY", "CODEX_BASE_URL", "CODEX_MODEL"):
        value = os.environ.get(name)
        if value is None:
            value = load_project_env_value(name)
        value = (value or "").strip()
        if not value:
            raise ValueError(
                f"Set {name} in process environment, root .env or agent-mini/.env"
            )
        values.append(value)
    api_key, base_url, model = values
    base_url = base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "CODEX_BASE_URL must be an HTTP(S) API prefix without credentials, query or fragment"
        )
    return api_key, base_url, model


def build_payload(question: str, model: str) -> dict:
    """One hosted tool makes 'required' an explicit search requirement."""
    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "instructions": WEBSEARCH_INSTRUCTIONS,
        "input": question,
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
    }


def build_request(question: str, api_key: str, *, base_url: str, model: str) -> Request:
    return Request(
        base_url.rstrip("/") + "/responses",
        data=json.dumps(build_payload(question, model)).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )


def inspect_response(response: dict) -> dict:
    """Inspect output items, never infer search from prose or citations alone."""
    calls, sources, citations, texts = [], [], [], []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            action = item.get("action")
            action = action if isinstance(action, dict) else {}
            safe_action = {
                key: action[key]
                for key in ("type", "query", "queries", "url", "pattern")
                if key in action
            }
            calls.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "action": safe_action,
                }
            )
            for source in action.get("sources") or []:
                if isinstance(source, dict) and source.get("url"):
                    sources.append(
                        {
                            "type": source.get("type"),
                            "title": source.get("title"),
                            "url": source["url"],
                        }
                    )
        elif item.get("type") == "message" and item.get("role") == "assistant":
            for block in item.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "output_text":
                    continue
                if isinstance(block.get("text"), str):
                    texts.append(block["text"])
                for annotation in block.get("annotations") or []:
                    if (
                        isinstance(annotation, dict)
                        and annotation.get("type") == "url_citation"
                        and annotation.get("url")
                    ):
                        citations.append(
                            {
                                key: annotation.get(key)
                                for key in ("title", "url", "start_index", "end_index")
                            }
                        )
    completed_searches = sum(
        call["status"] == "completed" and call["action"].get("type") == "search"
        for call in calls
    )
    answer = "\n".join(texts)
    evidence_present = bool(
        response.get("status") == "completed"
        and completed_searches
        and answer.strip()
        and (sources or citations)
    )
    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "status": response.get("status"),
        "incomplete_details": response.get("incomplete_details"),
        "error": response.get("error"),
        "usage": response.get("usage"),
        "web_search_calls": calls,
        "completed_search_calls": completed_searches,
        "sources": sources,
        "citations": citations,
        "answer": answer,
        "search_evidence_present": evidence_present,
    }


def safe_text(value: object, api_key: str) -> str:
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, indent=2)
    )
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"(?:sk-|sess-)[A-Za-z0-9_-]{12,}", "[REDACTED]", text)
    text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9_.-]{16,}", r"\1[REDACTED]", text)
    if len(text) > PRINT_LIMIT:
        return text[:PRINT_LIMIT] + "\n[output truncated]"
    return text


def main() -> int:
    question = (
        " ".join(sys.argv[1:]).strip()
        or "Search today's Hangzhou weather and cite sources."
    )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        api_key, base_url, model = load_config()
    except ValueError as error:
        LOGGER.error("Invalid configuration: %s", error)
        return 1
    LOGGER.info(
        "POST %s/responses; socket timeout=%ss; automatic retries=0",
        base_url,
        TIMEOUT_SECONDS,
    )
    LOGGER.info(
        "Request payload:\n%s", safe_text(build_payload(question, model), api_key)
    )
    start = perf_counter()
    try:
        with urlopen(
            build_request(question, api_key, base_url=base_url, model=model),
            timeout=TIMEOUT_SECONDS,
        ) as result:
            response = json.load(result)
        if not isinstance(response, dict):
            raise TypeError("Response JSON is not an object")
    except HTTPError as error:
        body = error.read(16384).decode("utf-8", errors="replace")
        LOGGER.error(
            "HTTP %s after %.2fs:\n%s",
            error.code,
            perf_counter() - start,
            safe_text(body, api_key),
        )
        return 1
    except (URLError, TimeoutError, TypeError, ValueError) as error:
        LOGGER.error(
            "Request failed after %.2fs: %s",
            perf_counter() - start,
            safe_text(str(error), api_key),
        )
        return 1
    report = inspect_response(response)
    LOGGER.info(
        "Response summary after %.2fs:\n%s",
        perf_counter() - start,
        safe_text(
            {
                key: value
                for key, value in report.items()
                if key not in ("answer", "sources", "citations")
            },
            api_key,
        ),
    )
    print("\n--- sources ---\n" + safe_text(report["sources"], api_key))
    print("\n--- citations ---\n" + safe_text(report["citations"], api_key))
    print("\n--- answer ---\n" + safe_text(report["answer"], api_key))
    if not report["search_evidence_present"]:
        LOGGER.warning(
            "Search unconfirmed: need completed response, completed search "
            "action, answer, and at least one source or URL citation."
        )
        return 2
    LOGGER.info("Returned JSON contains completed search, answer, and source evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
