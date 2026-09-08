"""Model boundary for LLM-backed structured planning."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib import error as url_error
from urllib import request as url_request

PlannerModelResponse = str | Mapping[str, object]


class PlannerModelError(RuntimeError):
    """Raised when the configured planning model cannot return a response."""


class StructuredPlanModel(Protocol):
    """Minimal provider interface required by :class:`LLMPlanner`."""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> PlannerModelResponse:
        """Return raw structured-plan content without executing any tools."""


@dataclass(frozen=True)
class OpenAICompatibleChatModel:
    """Small stdlib-only adapter for OpenAI-compatible chat completions."""

    model: str
    api_key: str = field(repr=False)
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        model = self.model.strip()
        api_key = self.api_key.strip()
        base_url = self.base_url.strip().rstrip("/")
        if not model:
            raise PlannerModelError("AGENT_MODEL 不能为空。")
        if not api_key:
            raise PlannerModelError("AGENT_API_KEY 不能为空。")
        if not base_url:
            raise PlannerModelError("AGENT_BASE_URL 不能为空。")
        if self.timeout_seconds <= 0:
            raise PlannerModelError("timeout_seconds 必须大于 0。")
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "base_url", base_url)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleChatModel:
        """Build the adapter from AGENT_* environment variables."""

        values = os.environ if environ is None else environ
        return cls(
            model=values.get("AGENT_MODEL", ""),
            api_key=values.get("AGENT_API_KEY", ""),
            base_url=values.get(
                "AGENT_BASE_URL",
                "https://api.openai.com/v1",
            ),
        )

    @property
    def endpoint(self) -> str:
        """Return the chat-completions endpoint for either base URL form."""

        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Call the model and return its text content for JSON validation."""

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = url_request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with url_request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                response_body = response.read()
        except url_error.HTTPError as exc:
            raise PlannerModelError(f"LLM 请求失败：HTTP {exc.code}。") from exc
        except url_error.URLError as exc:
            raise PlannerModelError("LLM 请求无法连接。") from exc
        except TimeoutError as exc:
            raise PlannerModelError("LLM 请求超时。") from exc

        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlannerModelError("LLM 返回的响应不是合法 JSON。") from exc
        return self._extract_content(decoded)

    @staticmethod
    def _extract_content(payload: object) -> str:
        if not isinstance(payload, Mapping):
            raise PlannerModelError("LLM 响应缺少 choices。")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise PlannerModelError("LLM 响应缺少 choices。")
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            raise PlannerModelError("LLM 响应的 choice 格式无效。")
        message = first_choice.get("message")
        if not isinstance(message, Mapping):
            raise PlannerModelError("LLM 响应缺少 message。")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, Mapping) and isinstance(part.get("text"), str)
            ]
            combined = "".join(text_parts).strip()
            if combined:
                return combined
        raise PlannerModelError("LLM 响应缺少可解析的 message.content。")
