"""组装并运行一次 Coding Agent。"""

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from langfuse import Langfuse, propagate_attributes
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from ..rag import OpenAIEmbedder
from ..tools import (
    MCPClientManager,
    ToolRegistry,
    register_fs_tools,
    register_grep_tool,
    register_read_file_tool,
    register_rag_tool,
    register_search_tools,
    register_shell_tools,
    register_subagent_tool,
)
from .checkpoint import (
    DEFAULT_RUNS_DIR,
    Checkpoint,
    CheckpointStatus,
    RunStatsSnapshot,
    save_checkpoint,
)
from .config import AgentSettings, ConfirmCallback
from .context import Context
from .cost import estimate_cost
from .git_snapshot import ensure_start_snapshot, get_head_sha
from .loop import AgentTrace, EventCallback, RunStats, message_text, run
from .logging_config import get_logger
from .prompts import build_system_prompt, build_task_message


ToolMode = Literal["all", "rag", "search"]
logger = get_logger("agent.runtime")


async def run_coding_agent(
    task: str,
    workdir: Path,
    settings: AgentSettings,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    max_tokens: int = 3000,
    context_window_tokens: int | None = None,
    max_cost_usd: float | None = None,
    run_id: str | None = None,
    enable_subagent: bool = True,
    tool_mode: ToolMode = "all",
    context: Context | None = None,
    stats: RunStats | None = None,
    start_turn: int = 0,
    checkpoint_enabled: bool = False,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    start_sha: str | None = None,
    event_callback: EventCallback | None = None,
    on_confirm: ConfirmCallback | None = None,
    trace_metadata: dict[str, Any] | None = None,
    trace_tags: list[str] | None = None,
    log_start: bool = True,
    log_completion: bool = True,
) -> tuple[ChatCompletion, RunStats]:
    """组装依赖并在指定目录运行一次 Coding Agent。"""
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise NotADirectoryError(f"工作目录不存在或不是目录: {workdir}")
    if tool_mode not in {"all", "rag", "search"}:
        raise ValueError(f"不支持的 tool_mode: {tool_mode}")
    selected_model = model if model is not None else settings.model
    selected_max_turns = (
        max_turns if max_turns is not None else settings.max_turns
    )
    selected_context_window_tokens = (
        context_window_tokens
        if context_window_tokens is not None
        else settings.context_window_tokens
    )
    if selected_context_window_tokens <= 0:
        raise ValueError("context_window_tokens 必须大于 0")
    selected_run_id = run_id or uuid4().hex
    selected_start_sha = start_sha
    if selected_start_sha is None:
        selected_start_sha = (
            ensure_start_snapshot(workdir)
            if checkpoint_enabled
            else get_head_sha(workdir)
        )
    trace = AgentTrace(
        run_id=selected_run_id,
        agent_id="main",
        role="main",
    )
    main_stats = stats if stats is not None else RunStats()
    run_started_at = perf_counter()

    registry = ToolRegistry()
    if tool_mode == "all":
        register_fs_tools(registry, workdir)
        register_search_tools(registry, workdir)
        register_shell_tools(
            registry,
            workdir,
            max_output_chars=settings.max_tool_output_chars,
            on_confirm=on_confirm,
        )
    elif tool_mode == "search":
        register_read_file_tool(registry, workdir)
        register_grep_tool(registry, workdir)

    if context is None:
        context = Context()
        context.append_user(build_task_message(task, workdir))
    else:
        context.assert_paired()

    def persist_checkpoint(
        current_context: Context,
        current_stats: RunStats,
        turn: int,
        status: CheckpointStatus,
    ) -> None:
        """在完整轮次边界保存可恢复状态。"""
        total_cost = estimate_cost(current_stats, settings)
        save_checkpoint(
            Checkpoint(
                run_id=selected_run_id,
                task=task,
                messages=current_context.messages,
                turn=turn,
                stats=RunStatsSnapshot.from_stats(current_stats),
                total_cost_usd=total_cost,
                workdir=str(workdir),
                model=selected_model,
                max_turns=selected_max_turns,
                max_tokens=max_tokens,
                context_window_tokens=selected_context_window_tokens,
                max_cost_usd=max_cost_usd,
                enable_subagent=enable_subagent,
                status=status,
                start_sha=selected_start_sha,
            ),
            runs_dir=runs_dir,
        )

    if checkpoint_enabled and start_turn == 0:
        persist_checkpoint(context, main_stats, 0, "running")

    def persist_failure_checkpoint(status: CheckpointStatus) -> None:
        """仅在消息完整配对时，记录可安全恢复的异常状态。"""
        try:
            context.assert_paired()
        except RuntimeError:
            # 工具调用尚未得到全部结果；保留上一份完整轮次的 checkpoint。
            return
        persist_checkpoint(context, main_stats, main_stats.turns, status)

    if log_start:
        logger.info(
            "Agent 开始: %s",
            trace.agent_id,
            extra={
                "event": "run.resumed" if start_turn else "run.started",
                "trace": trace.event_context(),
                "data": {
                    "task": task,
                    "workdir": str(workdir),
                    "model": selected_model,
                    "max_turns": selected_max_turns,
                    "start_turn": start_turn,
                },
            },
        )

    try:
        async with AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=0,
        ) as client:
            async with AsyncExitStack() as resource_stack:
                langfuse_client: Langfuse | None = None
                root_observation = None
                if settings.langfuse_configured:
                    langfuse_client = Langfuse(
                        public_key=settings.langfuse_public_key,
                        secret_key=settings.langfuse_secret_key,
                        base_url=settings.langfuse_base_url,
                    )
                    resource_stack.callback(langfuse_client.flush)
                    root_metadata = dict(trace_metadata or {})
                    root_metadata.update(
                        {
                            "run_id": selected_run_id,
                            "workdir": str(workdir),
                            "model": selected_model,
                            "max_turns": selected_max_turns,
                        }
                    )
                    if trace_metadata or trace_tags:
                        resource_stack.enter_context(
                            propagate_attributes(
                                metadata=trace_metadata or None,
                                tags=trace_tags or None,
                            )
                        )
                    root_observation = resource_stack.enter_context(
                        langfuse_client.start_as_current_observation(
                            as_type="agent",
                            name="agent-mini.run",
                            input={"task": task},
                            metadata=root_metadata,
                        )
                    )

                resource_context = ""
                if tool_mode in {"all", "rag"}:
                    embedding_client = await (
                        resource_stack.enter_async_context(
                            AsyncOpenAI(
                                api_key=(
                                    settings.embedding_api_key
                                    or settings.api_key
                                ),
                                base_url=(
                                    settings.embedding_base_url
                                    or settings.base_url
                                ),
                                max_retries=0,
                            )
                        )
                    )

                    def create_embedder(model: str) -> OpenAIEmbedder:
                        return OpenAIEmbedder(
                            embedding_client,
                            model=model,
                            batch_size=settings.embedding_batch_size,
                        )

                    register_rag_tool(
                        registry,
                        workdir,
                        embedder_factory=create_embedder,
                    )
                if settings.mcp_enabled and tool_mode == "all":
                    mcp_manager = await resource_stack.enter_async_context(
                        MCPClientManager(
                            settings.resolved_mcp_config_file
                        )
                    )
                    await mcp_manager.connect_all(registry)
                    resource_context = mcp_manager.resource_context
                if enable_subagent and tool_mode == "all":
                    register_subagent_tool(
                        registry,
                        client=client,
                        workdir=workdir,
                        model=selected_model,
                        parent_trace=trace,
                        parent_stats=main_stats,
                        prompt_cache=settings.prompt_cache_config,
                        context_window_tokens=selected_context_window_tokens,
                        langfuse_client=langfuse_client,
                    )
                result = await run(
                    client,
                    context,
                    registry,
                    model=selected_model,
                    system_prompt=build_system_prompt(resource_context),
                    max_turns=selected_max_turns,
                    max_tokens=max_tokens,
                    context_window_tokens=selected_context_window_tokens,
                    cost_estimator=lambda stats: estimate_cost(
                        stats, settings),
                    max_cost_usd=max_cost_usd,
                    prompt_cache=settings.prompt_cache_config,
                    stats=main_stats,
                    trace=trace,
                    start_turn=start_turn,
                    compact_enabled=settings.compact_enabled,
                    compact_threshold=settings.compact_threshold,
                    compact_keep_recent=settings.compact_keep_recent,
                    compact_model=settings.compact_model,
                    compact_max_tokens=settings.compact_max_tokens,
                    checkpoint_callback=(
                        persist_checkpoint if checkpoint_enabled else None
                    ),
                    event_callback=event_callback,
                    langfuse_client=langfuse_client,
                )
                if root_observation is not None:
                    final_response, final_stats = result
                    total_stats = final_stats.aggregate()
                    local_cost_usd = estimate_cost(final_stats, settings)
                    main_stats.trace_id = (
                        langfuse_client.get_current_trace_id()
                    )
                    trace_url = langfuse_client.get_trace_url()
                    main_stats.trace_url = trace_url
                    final_metadata = dict(root_metadata)
                    final_metadata.update(
                        {
                            "turns": total_stats.turns,
                            "input_tokens": total_stats.input_tokens,
                            "output_tokens": total_stats.output_tokens,
                            "cache_read_input_tokens": (
                                total_stats.cache_read_input_tokens
                            ),
                            "cache_creation_input_tokens": (
                                total_stats.cache_creation_input_tokens
                            ),
                            "local_cost_usd": local_cost_usd,
                            "trajectory": total_stats.trajectory_metrics(),
                        }
                    )
                    if trace_url is not None:
                        final_metadata["trace_url"] = trace_url
                    root_observation.update(
                        output={
                            "answer": message_text(
                                final_response.choices[0].message
                            )
                        },
                        metadata=final_metadata,
                    )
                if log_completion:
                    final_response, final_stats = result
                    logger.info(
                        "运行完成",
                        extra={
                            "event": "run.completed",
                            "trace": trace.event_context(final_stats.turns),
                            "data": {
                                "status": "completed",
                                "finish_reason": (
                                    final_response.choices[0].finish_reason
                                ),
                                "trace_id": final_stats.trace_id,
                                "trace_url": final_stats.trace_url,
                                "duration_s": round(
                                    perf_counter() - run_started_at,
                                    3,
                                ),
                            },
                        },
                    )
                return result
    except (asyncio.CancelledError, KeyboardInterrupt):
        if checkpoint_enabled:
            persist_failure_checkpoint("interrupted")
        raise
    except Exception as exc:
        logger.exception(
            "Agent 运行失败: %s",
            exc,
            extra={
                "event": "run.error",
                "trace": trace.event_context(),
                "data": {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "run_id": selected_run_id,
                    "rollback_run_id": selected_run_id,
                },
            },
        )
        if checkpoint_enabled:
            persist_failure_checkpoint("failed")
        raise
