"""Prompt cache request options shared by Agent and Workflow calls."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptCacheConfig:
    """Provider-neutral cache hints for OpenAI-compatible APIs."""

    enabled: bool = True
    key: str = "agent-mini"
    retention: str | None = None

    def request_kwargs(self) -> dict[str, Any]:
        """Return optional request fields without changing normal requests."""
        if not self.enabled:
            return {}

        extra_body: dict[str, Any] = {"prompt_cache_key": self.key}
        if self.retention:
            extra_body["prompt_cache_retention"] = self.retention
        return {"extra_body": extra_body}
