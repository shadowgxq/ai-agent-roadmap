"""Run and inspect one durable ticket workflow thread."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from support_agent.models import TicketAgentState


def build_thread_config(thread_id: str) -> RunnableConfig:
    """Build the persistence config without conflating ticket and thread IDs."""

    normalized_thread_id = thread_id.strip()
    if not normalized_thread_id:
        raise ValueError("thread_id 不能为空。")
    return {"configurable": {"thread_id": normalized_thread_id}}


async def start_run(graph: Any, state: TicketAgentState) -> dict[str, object]:
    """Start one graph run and persist it under the state's thread ID."""

    return await graph.ainvoke(
        state,
        config=build_thread_config(state["thread_id"]),
    )


async def get_run_snapshot(graph: Any, *, thread_id: str):
    """Read the latest checkpoint without executing the graph again."""

    return await graph.aget_state(build_thread_config(thread_id))
