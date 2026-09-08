"""Evidence-triggered re-planning and budgets for W16 Session 5."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from .plan import AgentPlan, PlanStep
from .planner import DeterministicPlanner, Planner, PlanningRequest


ReplanDecision = Literal["unchanged", "replanned", "blocked"]
ReplanStateStatus = Literal["active", "blocked"]


def _text_refs(value: Iterable[str], field_name: str) -> tuple[str, ...]:
    refs: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] 必须是非空字符串。")
        refs.append(item.strip())
    return tuple(refs)


@dataclass(frozen=True)
class ReplanBudget:
    """Hard limits that prevent an endless planning loop."""

    max_replans: int = 3
    max_steps: int = 20
    max_tool_calls: int = 50
    max_runtime_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_replans < 0:
            raise ValueError("max_replans 不能小于 0。")
        if self.max_steps <= 0:
            raise ValueError("max_steps 必须大于 0。")
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls 不能小于 0。")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds 必须大于 0。")

    def as_dict(self) -> dict[str, object]:
        return {
            "max_replans": self.max_replans,
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_runtime_seconds": self.max_runtime_seconds,
        }


@dataclass(frozen=True)
class ReplanObservation:
    """Runtime observation that may invalidate the current plan."""

    summary: str
    plan_invalidated: bool
    evidence_refs: tuple[str, ...]
    affected_step_ids: tuple[str, ...] = ()
    tool_calls_delta: int = 0
    runtime_seconds_delta: float = 0.0

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("observation summary 不能为空。")
        if not self.evidence_refs:
            raise ValueError("observation 必须包含 evidence_refs。")
        if self.tool_calls_delta < 0:
            raise ValueError("tool_calls_delta 不能小于 0。")
        if self.runtime_seconds_delta < 0:
            raise ValueError("runtime_seconds_delta 不能小于 0。")
        if not self.plan_invalidated and self.affected_step_ids:
            raise ValueError("计划未失效时不能声明 affected_step_ids。")

    def as_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "plan_invalidated": self.plan_invalidated,
            "evidence_refs": list(self.evidence_refs),
            "affected_step_ids": list(self.affected_step_ids),
            "tool_calls_delta": self.tool_calls_delta,
            "runtime_seconds_delta": self.runtime_seconds_delta,
        }


@dataclass(frozen=True)
class PlanRevision:
    """Audit record retaining both sides of one plan revision."""

    previous_plan: AgentPlan
    new_plan: AgentPlan
    trigger: ReplanObservation

    def as_dict(self) -> dict[str, object]:
        return {
            "previous_plan": self.previous_plan.as_dict(),
            "new_plan": self.new_plan.as_dict(),
            "trigger": self.trigger.as_dict(),
        }


@dataclass
class ReplanState:
    """Mutable state for plan versions, usage, and blocking."""

    plan: AgentPlan
    budget: ReplanBudget = ReplanBudget()
    history: tuple[PlanRevision, ...] = ()
    replan_count: int = 0
    tool_call_count: int = 0
    runtime_seconds: float = 0.0
    status: ReplanStateStatus = "active"
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        self.plan.validate()
        if self.replan_count < 0:
            raise ValueError("replan_count 不能小于 0。")
        if self.tool_call_count < 0:
            raise ValueError("tool_call_count 不能小于 0。")
        if self.runtime_seconds < 0:
            raise ValueError("runtime_seconds 不能小于 0。")
        if self.status not in ("active", "blocked"):
            raise ValueError("ReplanState.status 不合法。")
        if self.status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked 状态必须包含 blocked_reason。")

    @classmethod
    def create(
        cls,
        plan: AgentPlan,
        budget: ReplanBudget | None = None,
    ) -> "ReplanState":
        return cls(plan=plan, budget=budget or ReplanBudget())

    def record_usage(self, *, tool_calls: int, runtime_seconds: float) -> None:
        if tool_calls < 0 or runtime_seconds < 0:
            raise ValueError("usage 增量不能小于 0。")
        self.tool_call_count += tool_calls
        self.runtime_seconds += runtime_seconds

    def block(self, reason: str) -> None:
        self.status = "blocked"
        self.blocked_reason = reason

    def as_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.as_dict(),
            "budget": self.budget.as_dict(),
            "history": [revision.as_dict() for revision in self.history],
            "replan_count": self.replan_count,
            "tool_call_count": self.tool_call_count,
            "runtime_seconds": self.runtime_seconds,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ReplanResult:
    """Decision returned after inspecting one observation."""

    decision: ReplanDecision
    reason: str
    plan: AgentPlan
    replan_count: int
    status: ReplanStateStatus

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "plan": self.plan.as_dict(),
            "replan_count": self.replan_count,
            "status": self.status,
        }


class ReplanController:
    """Re-plan only when evidence invalidates the current task assumptions."""

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner or DeterministicPlanner()

    def consider(
        self,
        state: ReplanState,
        observation: ReplanObservation,
    ) -> ReplanResult:
        state.record_usage(
            tool_calls=observation.tool_calls_delta,
            runtime_seconds=observation.runtime_seconds_delta,
        )
        budget_reason = self._budget_reason(state)
        if budget_reason is not None:
            state.block(budget_reason)
            return ReplanResult(
                decision="blocked",
                reason=budget_reason,
                plan=state.plan,
                replan_count=state.replan_count,
                status=state.status,
            )

        if not observation.plan_invalidated:
            return ReplanResult(
                decision="unchanged",
                reason="当前证据没有改变原计划的任务假设，不触发无意义重规划。",
                plan=state.plan,
                replan_count=state.replan_count,
                status=state.status,
            )

        if state.replan_count >= state.budget.max_replans:
            reason = "已达到 max_replans，进入 blocked，等待人工介入。"
            state.block(reason)
            return ReplanResult(
                decision="blocked",
                reason=reason,
                plan=state.plan,
                replan_count=state.replan_count,
                status=state.status,
            )

        planning_result = self._planner.plan(
            PlanningRequest(
                goal=state.plan.goal,
                constraints=state.plan.constraints,
                available_tools=state.plan.available_tools,
                observations=(
                    observation.summary,
                    *observation.evidence_refs,
                    *(
                        f"受影响步骤：{step_id}"
                        for step_id in observation.affected_step_ids
                    ),
                ),
            )
        )
        if planning_result.plan is None:
            reason = "重规划结果无法形成结构化 AgentPlan，进入 blocked。"
            state.block(reason)
            return ReplanResult(
                decision="blocked",
                reason=reason,
                plan=state.plan,
                replan_count=state.replan_count,
                status=state.status,
            )
        if len(planning_result.plan.steps) > state.budget.max_steps:
            reason = "新计划超过 max_steps，进入 blocked。"
            state.block(reason)
            return ReplanResult(
                decision="blocked",
                reason=reason,
                plan=state.plan,
                replan_count=state.replan_count,
                status=state.status,
            )

        new_plan = _carry_forward_facts(
            previous_plan=state.plan,
            candidate_plan=planning_result.plan,
            affected_step_ids=observation.affected_step_ids,
        )
        new_plan = AgentPlan(
            goal=new_plan.goal,
            steps=new_plan.steps,
            version=state.plan.version + 1,
            constraints=new_plan.constraints,
            available_tools=new_plan.available_tools,
        )
        state.history = state.history + (
            PlanRevision(
                previous_plan=state.plan,
                new_plan=new_plan,
                trigger=observation,
            ),
        )
        state.plan = new_plan
        state.replan_count += 1
        return ReplanResult(
            decision="replanned",
            reason="证据表明原计划假设失效，已生成新版本并保留历史。",
            plan=new_plan,
            replan_count=state.replan_count,
            status=state.status,
        )

    @staticmethod
    def _budget_reason(state: ReplanState) -> str | None:
        if state.tool_call_count > state.budget.max_tool_calls:
            return "tool call budget 已超限，进入 blocked。"
        if state.runtime_seconds > state.budget.max_runtime_seconds:
            return "runtime budget 已超限，进入 blocked。"
        return None


def _carry_forward_facts(
    *,
    previous_plan: AgentPlan,
    candidate_plan: AgentPlan,
    affected_step_ids: tuple[str, ...],
) -> AgentPlan:
    """Preserve completed evidence except for steps invalidated by the observation."""

    previous_steps = {step.id: step for step in previous_plan.steps}
    affected = set(affected_step_ids)
    steps: list[PlanStep] = []
    for step in candidate_plan.steps:
        previous = previous_steps.get(step.id)
        if previous is not None and previous.status == "completed" and step.id not in affected:
            steps.append(
                replace(
                    step,
                    status="completed",
                    evidence_refs=previous.evidence_refs,
                )
            )
        else:
            steps.append(step)
    return AgentPlan(
        goal=candidate_plan.goal,
        steps=tuple(steps),
        version=candidate_plan.version,
        constraints=candidate_plan.constraints,
        available_tools=candidate_plan.available_tools,
    )
