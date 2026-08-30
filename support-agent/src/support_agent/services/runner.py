"""Run and inspect one durable ticket workflow thread."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from support_agent.models import ApprovalDecision, ApprovalResume, TicketAgentState
from support_agent.persistence.approvals import ApprovalRepository


class ThreadNotWaitingForApprovalError(RuntimeError):
    """The requested thread has no active approval interrupt."""


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


async def continue_run(graph: Any, *, thread_id: str) -> dict[str, object]:
    """Continue the same thread from its latest durable checkpoint."""

    config = build_thread_config(thread_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise LookupError(f"没有找到 thread_id={thread_id!r} 的 checkpoint。")
    return await graph.ainvoke(None, config=config)


async def resume_run(
    graph: Any,
    *,
    thread_id: str,
    decision: ApprovalDecision,
    actor_id: str,
    proposal_hash: str,
    approval_repository: ApprovalRepository,
    feedback: str | None = None,
) -> dict[str, object]:
    """Persist one decision, then resume the matching interrupted proposal."""

    resume_value = ApprovalResume(
        decision=decision,
        actor_id=actor_id,
        proposal_hash=proposal_hash,
        feedback=feedback,
    )
    config = build_thread_config(thread_id)
    snapshot = await graph.aget_state(config)
    values = dict(snapshot.values or {})
    has_interrupt = any(
        getattr(task, "interrupts", ())
        for task in (snapshot.tasks or ())
    )
    if not values or not has_interrupt:
        raise ThreadNotWaitingForApprovalError(
            f"thread_id={thread_id!r} 当前没有等待中的审批。"
        )

    current_proposal_hash = values.get("proposal_hash")
    if resume_value.proposal_hash == current_proposal_hash:
        await approval_repository.record_decision(
            organization_id=str(values["organization_id"]),
            ticket_id=str(values["ticket_id"]),
            run_id=str(values["run_id"]),
            thread_id=thread_id,
            actor_id=resume_value.actor_id,
            decision=resume_value.decision,
            feedback=resume_value.feedback,
            proposal_hash=resume_value.proposal_hash,
        )

    return await graph.ainvoke(
        Command(resume=resume_value.model_dump(exclude_none=True)),
        config=config,
    )
