"""Configure concise console output and append-only local JSONL events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any


LOGGER_NAME = "agent_mini"
LOCAL_EVENT_NAMES = frozenset(
    {
        "run.started",
        "run.resumed",
        "run.completed",
        "run.error",
        "run.interrupted",
        "llm.completed",
        "tool.completed",
        "agent.final_answer",
        "agent.completed",
    }
)
CONSOLE_EVENT_NAMES = frozenset(
    {
        *LOCAL_EVENT_NAMES,
        "agent.turn_started",
        "run.cost",
        "run.trace_url",
        "eval.started",
        "eval.case_started",
        "eval.case_completed",
        "eval.trace_url",
        "eval.completed",
        "eval.report_written",
    }
)
TEXT_PREVIEW_LIMIT = 240


def _preview(value: Any, limit: int = TEXT_PREVIEW_LIMIT) -> str:
    """把长文本压缩成适合本地排错日志的一行预览。"""
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\x00", "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated, total={len(text)} chars]"


def _normalize_data(event: str, data: Any) -> dict[str, Any]:
    """去掉运行日志中的完整输入、输出和 token 明细。"""
    if not isinstance(data, dict):
        return {"data": data}

    normalized = dict(data)
    if event == "run.started" or event == "run.resumed":
        if "task" in normalized:
            normalized["task_preview"] = _preview(normalized.pop("task"))
        normalized.pop("log_file", None)
    elif event == "llm.completed":
        if "text" in normalized:
            normalized["text_preview"] = _preview(normalized.pop("text"))
        calls = normalized.get("tool_calls")
        if isinstance(calls, list):
            normalized["tool_calls"] = [
                call.get("name", "<unknown>")
                if isinstance(call, dict)
                else str(call)
                for call in calls
            ]
    elif event == "tool.completed":
        content = normalized.pop("content", None)
        if content is not None:
            normalized.setdefault("result_size", len(str(content)))
            normalized.setdefault("preview", _preview(content))
        normalized.pop("arguments", None)
        if "error" in normalized:
            normalized["error"] = _preview(normalized["error"])
    elif event == "run.completed":
        # 最终回答由 agent.final_answer 单独完整保存，避免再次复制。
        normalized.pop("answer", None)
    elif event == "run.error":
        if "error" in normalized:
            normalized["error"] = _preview(normalized["error"])

    return normalized


class ConsoleFormatter(logging.Formatter):
    """优先显示事件提供的简洁控制台文本。"""

    def format(self, record: logging.LogRecord) -> str:
        return getattr(record, "console_message", record.getMessage())


class ConsoleEventFilter(logging.Filter):
    """只让面向人的关键进度事件进入终端。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "event", "log") in CONSOLE_EVENT_NAMES


class JsonEventFormatter(logging.Formatter):
    """把关键事件整理成一行、可直接被 jq/grep 消费的 JSON。"""

    def format_event(self, record: logging.LogRecord) -> dict[str, Any]:
        event = getattr(record, "event", "log")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": event,
        }
        trace = getattr(record, "trace", None)
        if isinstance(trace, dict):
            payload.update(trace)

        data = _normalize_data(event, getattr(record, "data", {}))
        payload.update(data)
        if event != "agent.final_answer":
            payload["message"] = _preview(record.getMessage())
        if record.exc_info:
            payload["exception"] = _preview(self.formatException(record.exc_info))
        return payload


class JsonFileHandler(logging.Handler):
    """Append each selected event as one UTF-8 JSONL record."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.event_formatter = JsonEventFormatter()
        self._lock = RLock()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "event", "log") not in LOCAL_EVENT_NAMES:
            return
        try:
            payload = self.event_formatter.format_event(record)
            with self._lock, self.path.open("a", encoding="utf-8") as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                file.write("\n")
                file.flush()
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger managed by agent-mini's logging configuration."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(log_file: Path) -> Path:
    """配置本次进程的 console，并向 JSONL 文件追加关键运行事件。"""
    path = log_file.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(ConsoleEventFilter())
    console_handler.setFormatter(ConsoleFormatter())
    logger.addHandler(console_handler)

    logger.addHandler(JsonFileHandler(path))
    return path
