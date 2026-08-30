"""W15 PostgreSQL recovery and replay scenarios without model calls."""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from support_agent.config import AgentSettings
from support_agent.graphs import SimulatedToolCrash, create_ticket_graph
from support_agent.models import ApprovalDecision, TicketAgentState
from support_agent.persistence import (
    ApprovalRepository,
    MockCrmRepository,
    ToolActionRepository,
    create_checkpointer,
    initialize_business_schema,
)
from support_agent.services import (
    ThreadNotWaitingForApprovalError,
    continue_run,
    get_run_snapshot,
    resume_run,
    start_run,
)


@dataclass(frozen=True)
class RecoveryCase:
    organization_id: str
    ticket_id: str
    run_id: str
    thread_id: str


def _new_case() -> RecoveryCase:
    suffix = uuid4().hex
    return RecoveryCase(
        organization_id=f"org_{suffix}",
        ticket_id=f"ticket_{suffix}",
        run_id=f"run_{suffix}",
        thread_id=f"thread_{suffix}",
    )


def _initial_state(case: RecoveryCase) -> TicketAgentState:
    return {
        "organization_id": case.organization_id,
        "user_id": "user_w15_recovery",
        "ticket_id": case.ticket_id,
        "run_id": case.run_id,
        "thread_id": case.thread_id,
        "subject": "请直接更新 CRM 工单",
        "description": "工单信息完整，请将 CRM 状态更新为 resolved。",
        "customer_tier": "standard",
        "status": "pending",
        "category": "account",
        "priority": "high",
        "missing_fields": [],
        "revision_count": 0,
    }


def _offline_response(state: TicketAgentState) -> dict[str, object]:
    revision_count = state.get("revision_count", 0)
    feedback = state.get("approval_feedback")
    if feedback:
        draft = f"修订版 {revision_count}：{feedback}"
    else:
        draft = "准备将 CRM 工单状态更新为 resolved。"
    return {
        "draft_response": draft,
        "risk_level": "high",
        "risk_reasons": ["该操作会修改 CRM 工单状态。"],
        "requires_approval": True,
        "status": "assessed",
    }


def _offline_response_subgraph():
    builder = StateGraph(TicketAgentState)
    builder.add_node("offline_response", _offline_response)
    builder.add_edge(START, "offline_response")
    builder.add_edge("offline_response", END)
    return builder.compile()


def _create_graph(
    checkpointer,
    database_url: str,
    *,
    crash_before_tool: bool = False,
    crash_after_tool_commit: bool = False,
    interrupt_before: list[str] | None = None,
):
    crm_repository = MockCrmRepository(database_url)
    return create_ticket_graph(
        checkpointer=checkpointer,
        response_subgraph=_offline_response_subgraph(),
        tool_executor=crm_repository.update_ticket,
        crash_before_tool=crash_before_tool,
        crash_after_tool_commit=crash_after_tool_commit,
        interrupt_before=interrupt_before,
    )


def _is_waiting_for_approval(snapshot: object) -> bool:
    return any(
        getattr(task, "interrupts", ())
        for task in (getattr(snapshot, "tasks", ()) or ())
    )


def _proposal_hash(snapshot: object) -> str:
    value = dict(getattr(snapshot, "values", {}) or {}).get("proposal_hash")
    assert isinstance(value, str)
    return value


async def _start_until_approval(
    database_url: str,
    case: RecoveryCase,
):
    async with create_checkpointer(database_url) as checkpointer:
        graph = _create_graph(checkpointer, database_url)
        await start_run(graph, _initial_state(case))
        snapshot = await get_run_snapshot(graph, thread_id=case.thread_id)
    assert _is_waiting_for_approval(snapshot)
    return snapshot


async def _resume_decision(
    database_url: str,
    case: RecoveryCase,
    *,
    decision: ApprovalDecision,
    proposal_hash: str,
    feedback: str | None = None,
    crash_before_tool: bool = False,
    crash_after_tool_commit: bool = False,
):
    approval_repository = ApprovalRepository(database_url)
    async with create_checkpointer(database_url) as checkpointer:
        graph = _create_graph(
            checkpointer,
            database_url,
            crash_before_tool=crash_before_tool,
            crash_after_tool_commit=crash_after_tool_commit,
        )
        result = await resume_run(
            graph,
            thread_id=case.thread_id,
            decision=decision,
            actor_id="reviewer_w15",
            proposal_hash=proposal_hash,
            approval_repository=approval_repository,
            feedback=feedback,
        )
        snapshot = await get_run_snapshot(graph, thread_id=case.thread_id)
    return result, snapshot


async def _continue_after_restart(
    database_url: str,
    case: RecoveryCase,
):
    async with create_checkpointer(database_url) as checkpointer:
        graph = _create_graph(checkpointer, database_url)
        result = await continue_run(graph, thread_id=case.thread_id)
        snapshot = await get_run_snapshot(graph, thread_id=case.thread_id)
    return result, snapshot


async def _business_records(database_url: str, case: RecoveryCase):
    approvals = await ApprovalRepository(database_url).list_for_run(case.run_id)
    actions = await ToolActionRepository(database_url).list_for_run(case.run_id)
    crm_ticket = await MockCrmRepository(database_url).get_ticket(
        organization_id=case.organization_id,
        ticket_id=case.ticket_id,
    )
    return approvals, actions, crm_ticket


@pytest.fixture(scope="module")
def database_url() -> str:
    return AgentSettings().database_url


def test_restart_before_dynamic_interrupt_reaches_approval(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()

        async with create_checkpointer(database_url) as checkpointer:
            graph = _create_graph(
                checkpointer,
                database_url,
                interrupt_before=["approval_gate"],
            )
            await start_run(graph, _initial_state(case))
            before_restart = await get_run_snapshot(
                graph,
                thread_id=case.thread_id,
            )

        assert tuple(before_restart.next) == ("approval_gate",)

        _, after_restart = await _continue_after_restart(database_url, case)
        assert _is_waiting_for_approval(after_restart)
        assert dict(after_restart.values)["status"] == "assessed"

        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert approvals == []
        assert actions == []
        assert crm_ticket is None

    asyncio.run(scenario())


def test_restart_while_waiting_preserves_interrupt(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()
        before_restart = await _start_until_approval(database_url, case)
        original_hash = _proposal_hash(before_restart)

        async with create_checkpointer(database_url) as checkpointer:
            graph = _create_graph(checkpointer, database_url)
            after_restart = await get_run_snapshot(
                graph,
                thread_id=case.thread_id,
            )

        assert _is_waiting_for_approval(after_restart)
        assert _proposal_hash(after_restart) == original_hash
        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert approvals == []
        assert actions == []
        assert crm_ticket is None

    asyncio.run(scenario())


def test_crash_before_tool_executes_crm_once_after_restart(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()
        waiting = await _start_until_approval(database_url, case)

        with pytest.raises(
            SimulatedToolCrash,
            match="before external side effect",
        ):
            await _resume_decision(
                database_url,
                case,
                decision="approve",
                proposal_hash=_proposal_hash(waiting),
                crash_before_tool=True,
            )

        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert len(approvals) == 1
        assert actions == []
        assert crm_ticket is None

        _, completed = await _continue_after_restart(database_url, case)
        values = dict(completed.values)
        assert values["status"] == "completed"
        assert values["tool_replayed"] is False

        _, actions, crm_ticket = await _business_records(database_url, case)
        assert len(actions) == 1
        assert actions[0].status == "succeeded"
        assert crm_ticket is not None
        assert crm_ticket.update_count == 1

    asyncio.run(scenario())


def test_crash_after_tool_commit_replays_saved_result(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()
        waiting = await _start_until_approval(database_url, case)

        with pytest.raises(
            SimulatedToolCrash,
            match="after external side effect",
        ):
            await _resume_decision(
                database_url,
                case,
                decision="approve",
                proposal_hash=_proposal_hash(waiting),
                crash_after_tool_commit=True,
            )

        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert len(approvals) == 1
        assert len(actions) == 1
        assert actions[0].status == "succeeded"
        assert crm_ticket is not None
        assert crm_ticket.update_count == 1

        _, completed = await _continue_after_restart(database_url, case)
        values = dict(completed.values)
        assert values["status"] == "completed"
        assert values["tool_replayed"] is True

        _, replayed_actions, replayed_crm = await _business_records(
            database_url,
            case,
        )
        assert len(replayed_actions) == 1
        assert replayed_crm is not None
        assert replayed_crm.update_count == 1

    asyncio.run(scenario())


def test_duplicate_approve_cannot_create_duplicate_side_effect(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()
        waiting = await _start_until_approval(database_url, case)
        proposal_hash = _proposal_hash(waiting)

        _, completed = await _resume_decision(
            database_url,
            case,
            decision="approve",
            proposal_hash=proposal_hash,
        )
        assert dict(completed.values)["status"] == "completed"

        with pytest.raises(ThreadNotWaitingForApprovalError):
            await _resume_decision(
                database_url,
                case,
                decision="approve",
                proposal_hash=proposal_hash,
            )

        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert len(approvals) == 1
        assert len(actions) == 1
        assert crm_ticket is not None
        assert crm_ticket.update_count == 1

    asyncio.run(scenario())


def test_old_approval_is_invalid_after_revision(
    database_url: str,
) -> None:
    async def scenario() -> None:
        await initialize_business_schema(database_url)
        case = _new_case()
        first_waiting = await _start_until_approval(database_url, case)
        old_hash = _proposal_hash(first_waiting)

        _, revised = await _resume_decision(
            database_url,
            case,
            decision="revise",
            proposal_hash=old_hash,
            feedback="请明确说明只更新 CRM 状态。",
        )
        new_hash = _proposal_hash(revised)
        assert new_hash != old_hash
        assert _is_waiting_for_approval(revised)

        _, stale_approval = await _resume_decision(
            database_url,
            case,
            decision="approve",
            proposal_hash=old_hash,
        )
        values = dict(stale_approval.values)
        assert _is_waiting_for_approval(stale_approval)
        assert values["proposal_hash"] == new_hash
        assert "审批内容已经变化" in str(values["approval_error"])

        approvals, actions, crm_ticket = await _business_records(
            database_url,
            case,
        )
        assert len(approvals) == 1
        assert approvals[0].decision == "revise"
        assert approvals[0].proposal_hash == old_hash
        assert actions == []
        assert crm_ticket is None

    asyncio.run(scenario())
