"""Workflow 节点共享的模型调用与观测能力。"""

from dataclasses import dataclass

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from ..agent.loop import extract_usage_tokens


@dataclass
class WorkflowStats:
    """累计一次 Workflow 运行中的模型调用与 token 用量。"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """返回普通输入、缓存输入和输出 token 总数。"""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    def record(self, response: ChatCompletion) -> None:
        """把一次模型响应的 usage 累加到统计中。"""
        usage = extract_usage_tokens(response.usage)
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_input_tokens += usage.cache_read_input_tokens
        self.cache_creation_input_tokens += (
            usage.cache_creation_input_tokens
        )


class WorkflowRuntime:
    """为 Workflow 节点提供统一的文本生成入口。"""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        stats: WorkflowStats | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.stats = stats or WorkflowStats()

    async def complete(
        self,
        *,
        step_name: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        """执行一次无工具的模型调用，并记录用量和输出摘要。"""
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        output = (response.choices[0].message.content or "").strip()
        self.stats.record(response)
        self._log_step(step_name, response, output)
        return output

    @staticmethod
    def _log_step(
        step_name: str,
        response: ChatCompletion,
        output: str,
    ) -> None:
        """打印单个节点的 token 用量和输出摘要。"""
        usage = extract_usage_tokens(response.usage)
        preview = " ".join(output.split())
        if len(preview) > 120:
            preview = f"{preview[:120]}..."
        print(
            f"[workflow] {step_name}: "
            f"input_tokens={usage.input_tokens}, "
            f"output_tokens={usage.output_tokens}, "
            f"output={preview or '(空)'}"
        )
