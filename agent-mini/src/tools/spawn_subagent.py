"""探索型 SubAgent 工具。"""

from pathlib import Path
from uuid import uuid4

from langfuse import Langfuse
from openai import AsyncOpenAI

from ..agent.cache import PromptCacheConfig
from ..agent.context import Context
from ..agent.loop import AgentTrace, RunStats, message_text, run
from .fs import register_readonly_fs_tools
from .registry import ToolRegistry
from .search import register_search_tools


SUBAGENT_SYSTEM_PROMPT = """
你是一个只读的项目探索助手。

根据分配给你的子任务搜索和阅读项目代码，但不要修改任何文件。
重点识别关键文件、代码关系、实现行为和潜在问题。

完成探索后，返回不超过 500 token 的结构化总结：
1. 关键结论
2. 相关文件
3. 支撑结论的代码事实

不要返回完整文件内容，也不要描述无关的探索过程。
""".strip()


def register_subagent_tool(
    registry: ToolRegistry,
    *,
    client: AsyncOpenAI,
    workdir: Path,
    model: str,
    parent_trace: AgentTrace,
    parent_stats: RunStats,
    prompt_cache: PromptCacheConfig | None = None,
    max_tokens: int = 1000,
    context_window_tokens: int = 128_000,
    langfuse_client: Langfuse | None = None,
) -> None:
    """注册绑定到当前模型和工作目录的探索型 SubAgent。"""

    @registry.tool
    async def spawn_subagent(task: str) -> str:
        """派出只读 SubAgent 探索复杂问题并返回简短总结。

        适用于需要搜索多个文件、理解模块结构或追踪调用关系的子任务。
        不适用于读取单个已知文件或直接执行小范围代码修改。

        Args:
            task: 明确且可独立完成的探索任务。
        """
        child_registry = ToolRegistry()
        register_readonly_fs_tools(child_registry, workdir)
        register_search_tools(child_registry, workdir)

        child_context = Context()
        child_context.append_user(task)
        child_stats = RunStats()
        parent_stats.subagent_runs.append(child_stats)
        child_trace = AgentTrace(
            run_id=parent_trace.run_id,
            agent_id=f"subagent-{uuid4().hex[:8]}",
            parent_agent_id=parent_trace.agent_id,
            role="subagent",
        )

        response, _ = await run(
            client,
            child_context,
            child_registry,
            model=model,
            system_prompt=SUBAGENT_SYSTEM_PROMPT,
            max_turns=15,
            max_tokens=max_tokens,
            context_window_tokens=context_window_tokens,
            prompt_cache=prompt_cache,
            stats=child_stats,
            trace=child_trace,
            langfuse_client=langfuse_client,
        )

        summary = message_text(response.choices[0].message)

        if not summary:
            raise RuntimeError("SubAgent 没有返回最终总结")
        return summary
