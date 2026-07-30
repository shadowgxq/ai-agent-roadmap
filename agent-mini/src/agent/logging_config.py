"""Configure plain console logs and a structured JSON event file."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


LOGGER_NAME = "agent_mini"


class ConsoleFormatter(logging.Formatter):
    """优先显示事件提供的详细控制台文本。"""

    def format(self, record: logging.LogRecord) -> str:
        return getattr(record, "console_message", record.getMessage())


class JsonEventFormatter(logging.Formatter):
    """Convert a log record to a JSON-serializable event."""

    def format_event(
        self,
        record: logging.LogRecord,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).astimezone().isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        trace = getattr(record, "trace", None)
        if trace:
            payload["trace"] = trace
        data = getattr(record, "data", None)
        if data:
            payload["data"] = data
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return payload


class JsonFileHandler(logging.Handler):
    """Keep the target file as one complete, readable JSON document."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.events: list[dict[str, Any]] = []
        self.event_formatter = JsonEventFormatter()
        self._write_document()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.events.append(self.event_formatter.format_event(record))
            self._write_document()
        except Exception:
            self.handleError(record)

    def _write_document(self) -> None:
        document = {
            "schema_version": 2,
            "event_count": len(self.events),
            "events": self.events,
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(document, file, ensure_ascii=False, indent=2, default=str)
            file.write("\n")
        temporary_path.replace(self.path)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger managed by agent-mini's logging configuration."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(log_file: Path) -> Path:
    """Clear the target file and write this run as one JSON document."""
    path = log_file.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ConsoleFormatter())
    logger.addHandler(console_handler)

    file_handler = JsonFileHandler(path)
    logger.addHandler(file_handler)
    return path
