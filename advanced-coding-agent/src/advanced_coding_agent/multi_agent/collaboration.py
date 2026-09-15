"""W18 Session 2 Manager/Worker contracts.

The Manager builds a fixed role pipeline and evaluates structured Worker
results.  No model, tool, routing, retry loop, or parallel executor is
started here; later sessions add those runtime behaviours around these
contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal

from .decision import (
    SplitDecision,
    SplitDecisionValidationError,
    WorkerBoundary,
    WorkerRole,
    default_worker_boundaries,
)
from .routing import RouteDecision, RouteRecovery

WorkerStatus = Literal[
    "assigned",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "needs_review",
]
ManagerAction = Literal["accept", "retry", "reassign", "pause"]
TraceEventKind = Literal["assignment", "result", "decision"]
_WORKER_ROLES: tuple[WorkerRole, ...] = ("researcher", "coder", "tester")
_WORKER_STATUSES = frozenset(
    {"assigned", "running", "succeeded", "failed", "blocked", "needs_review"}
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SplitDecisionValidationError(f"{name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SplitDecisionValidationError(f"{name} 必须是字符串数组。")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise SplitDecisionValidationError(f"{name} 不能重复。")
    return result


@dataclass(frozen=True)
class RoleSpec:
    """Prompt, tools, budget, and boundary for one role."""

    role: WorkerRole
    boundary: WorkerBoundary
    role_prompt: str
    timeout_seconds: float = 120.0
    max_tool_calls: int = 12

    def __post_init__(self) -> None:
        _text(self.role_prompt, f"{self.role}.role_prompt")
        if self.timeout_seconds <= 0 or self.max_tool_calls <= 0:
            raise SplitDecisionValidationError(f"{self.role} budget 必须大于 0。")
        if self.boundary.role != self.role:
            raise SplitDecisionValidationError(
                "RoleSpec 与 WorkerBoundary 角色不一致。")

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "role_prompt": self.role_prompt,
            "timeout_seconds": self.timeout_seconds,
            "max_tool_calls": self.max_tool_calls,
            "boundary": asdict(self.boundary),
        }


def default_role_specs(
    *,
    timeout_seconds: float = 120.0,
    max_tool_calls: int = 12,
) -> tuple[RoleSpec, ...]:
    """Return fixed prompts and budgets; execution is intentionally separate."""

    boundaries = {item.role: item for item in default_worker_boundaries()}
    prompts = {
        "manager": "只负责拆分、分配、聚合和状态决策，不直接修改业务代码。",
        "researcher": "只读搜索目标范围，返回带 evidence 引用的研究结论。",
        "coder": "只依据 Manager 接受的 evidence 做最小修改，并返回变更证据。",
        "tester": "只根据成功标准和 diff 做独立验证，返回 pass/fail/review 证据。",
    }
    return tuple(
        RoleSpec(
            role=role,
            boundary=boundaries[role],
            role_prompt=prompts[role],
            timeout_seconds=timeout_seconds,
            max_tool_calls=max_tool_calls,
        )
        for role in ("manager", "researcher", "coder", "tester")
    )


@dataclass(frozen=True)
class WorkerAssignment:
    """The smallest context and authority handed to one Worker."""

    assignment_id: str
    task_id: str
    role: WorkerRole
    objective: str
    constraints: tuple[str, ...]
    input_context: tuple[str, ...]
    dependencies: tuple[str, ...]
    role_spec: RoleSpec
    status: WorkerStatus = "assigned"

    def __post_init__(self) -> None:
        if self.role not in _WORKER_ROLES:
            raise SplitDecisionValidationError(
                "WorkerAssignment.role 只能是 researcher、coder 或 tester。"
            )
        if self.role_spec.role != self.role:
            raise SplitDecisionValidationError(
                "assignment role 与 role_spec 不一致。")
        if self.status not in _WORKER_STATUSES:
            raise SplitDecisionValidationError("assignment status 不合法。")
        _text(self.assignment_id, "assignment.assignment_id")
        _text(self.task_id, "assignment.task_id")
        _text(self.objective, "assignment.objective")
        _texts(self.constraints, "assignment.constraints")
        _texts(self.input_context, "assignment.input_context")
        _texts(self.dependencies, "assignment.dependencies")

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "role": self.role,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "input_context": list(self.input_context),
            "dependencies": list(self.dependencies),
            "status": self.status,
            "role_spec": self.role_spec.as_dict(),
        }


@dataclass(frozen=True)
class WorkerResult:
    """Common result envelope returned by every Worker role."""

    assignment_id: str
    task_id: str
    role: WorkerRole
    status: WorkerStatus
    summary: str
    evidence_refs: tuple[str, ...] = ()
    recommendation: str = ""
    tool_call_ids: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.role not in _WORKER_ROLES:
            raise SplitDecisionValidationError("WorkerResult.role 不合法。")
        if self.status not in _WORKER_STATUSES:
            raise SplitDecisionValidationError("WorkerResult.status 不合法。")
        _text(self.assignment_id, "result.assignment_id")
        _text(self.task_id, "result.task_id")
        _text(self.summary, "result.summary")
        _texts(self.evidence_refs, "result.evidence_refs")
        _texts(self.tool_call_ids, "result.tool_call_ids")
        _texts(self.changed_files, "result.changed_files")
        if self.status == "failed" and not self.failure_reason:
            raise SplitDecisionValidationError(
                "failed result 必须包含 failure_reason。")

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "role": self.role,
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "recommendation": self.recommendation,
            "tool_call_ids": list(self.tool_call_ids),
            "changed_files": list(self.changed_files),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ManagerDecision:
    """Manager's next action after inspecting one structured Worker result."""

    assignment_id: str
    action: ManagerAction
    reason: str
    retry_count: int = 0
    next_role: WorkerRole | None = None
    accepted_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.action not in ("accept", "retry", "reassign", "pause"):
            raise SplitDecisionValidationError("ManagerDecision.action 不合法。")
        if self.retry_count < 0:
            raise SplitDecisionValidationError("retry_count 不能小于 0。")
        if self.action == "reassign" and self.next_role not in _WORKER_ROLES:
            raise SplitDecisionValidationError("reassign 必须指定合法 next_role。")
        if self.action != "reassign" and self.next_role is not None:
            raise SplitDecisionValidationError("只有 reassign 可以指定 next_role。")
        _text(self.assignment_id, "decision.assignment_id")
        _text(self.reason, "decision.reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "action": self.action,
            "reason": self.reason,
            "retry_count": self.retry_count,
            "next_role": self.next_role,
            "accepted_evidence_refs": list(self.accepted_evidence_refs),
        }


@dataclass(frozen=True)
class CollaborationPlan:
    """A fixed Manager-created pipeline for one complete task."""

    goal_id: str
    objective: str
    constraints: tuple[str, ...]
    success_criteria: tuple[str, ...]
    manager_spec: RoleSpec
    assignments: tuple[WorkerAssignment, ...]

    def __post_init__(self) -> None:
        _text(self.goal_id, "goal_id")
        _text(self.objective, "objective")
        if not self.success_criteria:
            raise SplitDecisionValidationError("success_criteria 不能为空。")
        assignment_ids = tuple(item.assignment_id for item in self.assignments)
        if len(assignment_ids) != len(set(assignment_ids)):
            raise SplitDecisionValidationError("assignment_id 不能重复。")
        known = set(assignment_ids)
        for assignment in self.assignments:
            missing = set(assignment.dependencies) - known
            if missing:
                raise SplitDecisionValidationError(
                    f"assignment {assignment.assignment_id} 缺少依赖：{', '.join(missing)}。"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "success_criteria": list(self.success_criteria),
            "manager_spec": self.manager_spec.as_dict(),
            "assignments": [item.as_dict() for item in self.assignments],
        }


@dataclass(frozen=True)
class CollaborationEvent:
    sequence: int
    kind: TraceEventKind
    actor: WorkerRole
    assignment_id: str
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "actor": self.actor,
            "assignment_id": self.assignment_id,
            "payload": dict(self.payload),
        }


@dataclass
class CollaborationTrace:
    """Append-only observability for assignments, results, and decisions."""

    _events: list[CollaborationEvent] = field(default_factory=list, repr=False)

    @property
    def events(self) -> tuple[CollaborationEvent, ...]:
        return tuple(self._events)

    def record_assignment(self, assignment: WorkerAssignment) -> CollaborationEvent:
        return self._record(
            "assignment",
            assignment.role,
            assignment.assignment_id,
            assignment.as_dict(),
        )

    def record_result(self, result: WorkerResult) -> CollaborationEvent:
        return self._record("result", result.role, result.assignment_id, result.as_dict())

    def record_decision(self, decision: ManagerDecision) -> CollaborationEvent:
        return self._record(
            "decision",
            "manager",
            decision.assignment_id,
            decision.as_dict(),
        )

    def _record(
        self,
        kind: TraceEventKind,
        actor: WorkerRole,
        assignment_id: str,
        payload: Mapping[str, object],
    ) -> CollaborationEvent:
        event = CollaborationEvent(
            sequence=len(self._events) + 1,
            kind=kind,
            actor=actor,
            assignment_id=assignment_id,
            payload=dict(payload),
        )
        self._events.append(event)
        return event

    def as_dict(self) -> dict[str, object]:
        return {"events": [event.as_dict() for event in self._events]}


class Manager:
    """Create the fixed Session 2 pipeline and evaluate Worker outcomes."""

    def __init__(
        self,
        role_specs: tuple[RoleSpec, ...] | None = None,
        *,
        max_retries: int = 1,
    ) -> None:
        specs = role_specs or default_role_specs()
        self._role_specs = {spec.role: spec for spec in specs}
        if "manager" not in self._role_specs:
            raise SplitDecisionValidationError("Manager spec 不能为空。")
        if max_retries < 0:
            raise SplitDecisionValidationError("max_retries 不能小于 0。")
        self.max_retries = max_retries

    @property
    def spec(self) -> RoleSpec:
        return self._role_specs["manager"]

    def create_plan(
        self,
        *,
        goal_id: str,
        objective: str,
        constraints: tuple[str, ...],
        success_criteria: tuple[str, ...],
        decision: SplitDecision,
    ) -> CollaborationPlan:
        """Build a fixed Research → Code → Test pipeline from Session 1's decision."""

        if decision.mode != "multi-agent":
            raise SplitDecisionValidationError(
                "只有 multi-agent SplitDecision 才能创建 Manager/Worker plan。"
            )
        selected = {boundary.role for boundary in decision.worker_boundaries}
        assignments: list[WorkerAssignment] = []
        researcher_id: str | None = None
        coder_id: str | None = None

        if "researcher" in selected:
            researcher_id = f"{goal_id}:research"
            assignments.append(
                self._assignment(
                    assignment_id=researcher_id,
                    task_id=f"research:{goal_id}",
                    role="researcher",
                    objective=f"研究并定位：{objective}",
                    constraints=constraints,
                    input_context=("goal", "constraints",
                                   "bounded_search_scope"),
                    dependencies=(),
                )
            )
        if "coder" in selected:
            coder_id = f"{goal_id}:code"
            assignments.append(
                self._assignment(
                    assignment_id=coder_id,
                    task_id=f"code:{goal_id}",
                    role="coder",
                    objective=f"根据已接受 evidence 修改：{objective}",
                    constraints=constraints,
                    input_context=("goal", "constraints",
                                   "accepted_research_evidence"),
                    dependencies=(researcher_id,) if researcher_id else (),
                )
            )
        if "tester" in selected:
            assignments.append(
                self._assignment(
                    assignment_id=f"{goal_id}:test",
                    task_id=f"test:{goal_id}",
                    role="tester",
                    objective=f"验证任务是否满足成功标准：{objective}",
                    constraints=constraints,
                    input_context=("success_criteria",
                                   "changed_files", "diff"),
                    dependencies=(coder_id,) if coder_id else (),
                )
            )
        return CollaborationPlan(
            goal_id=goal_id,
            objective=objective,
            constraints=constraints,
            success_criteria=success_criteria,
            manager_spec=self.spec,
            assignments=tuple(assignments),
        )

    def evaluate_result(
        self,
        result: WorkerResult,
        *,
        retry_count: int = 0,
        reassign_to: WorkerRole | None = None,
    ) -> ManagerDecision:
        """Choose a next action without executing it."""

        if result.status == "succeeded":
            if not result.evidence_refs:
                return ManagerDecision(
                    assignment_id=result.assignment_id,
                    action="pause",
                    reason="Worker 声称成功但没有 evidence，不能接受。",
                    retry_count=retry_count,
                )
            return ManagerDecision(
                assignment_id=result.assignment_id,
                action="accept",
                reason="结果状态成功且 evidence 完整。",
                retry_count=retry_count,
                accepted_evidence_refs=result.evidence_refs,
            )
        if result.status == "failed":
            if reassign_to is not None:
                self._assert_reassignable(result.role, reassign_to)
                return ManagerDecision(
                    assignment_id=result.assignment_id,
                    action="reassign",
                    reason="当前 Worker 失败，改派给明确的替代角色。",
                    retry_count=retry_count,
                    next_role=reassign_to,
                )
            if retry_count < self.max_retries:
                return ManagerDecision(
                    assignment_id=result.assignment_id,
                    action="retry",
                    reason="失败原因仍在有限重试预算内。",
                    retry_count=retry_count + 1,
                )
        return ManagerDecision(
            assignment_id=result.assignment_id,
            action="pause",
            reason="结果被阻塞、需要 review，或已耗尽安全处理路径。",
            retry_count=retry_count,
        )

    def recover_route(
        self,
        decision: RouteDecision,
        *,
        reassign_to: WorkerRole | None = None,
    ) -> RouteRecovery:
        """Handle an unsafe or unknown route without choosing a Worker blindly."""

        if decision.status == "routed":
            raise SplitDecisionValidationError(
                "只有 needs_review 或 blocked route 才需要 Manager recovery。"
            )
        if reassign_to is not None:
            if reassign_to not in _WORKER_ROLES:
                raise SplitDecisionValidationError(
                    "route recovery 的 reassign_to 必须是 Worker 角色。"
                )
            if reassign_to not in self._role_specs:
                raise SplitDecisionValidationError(
                    f"缺少 {reassign_to} RoleSpec，不能改派。"
                )
            return RouteRecovery(
                task_id=decision.task_id,
                action="reassign",
                reason="Manager 根据路由失败原因选择了明确的替代 Worker。",
                next_role=reassign_to,
            )
        if decision.status == "blocked" or decision.fallback == "blocked":
            return RouteRecovery(
                task_id=decision.task_id,
                action="blocked",
                reason="路由失败且 fallback 禁止继续自动执行。",
            )
        return RouteRecovery(
            task_id=decision.task_id,
            action="manager_review",
            reason="路由失败，等待 Manager 补充上下文或人工确认。",
        )

    def build_trace(self, plan: CollaborationPlan) -> CollaborationTrace:
        trace = CollaborationTrace()
        for assignment in plan.assignments:
            trace.record_assignment(assignment)
        return trace

    def _assignment(
        self,
        *,
        assignment_id: str,
        task_id: str,
        role: WorkerRole,
        objective: str,
        constraints: tuple[str, ...],
        input_context: tuple[str, ...],
        dependencies: tuple[str, ...],
    ) -> WorkerAssignment:
        if role not in self._role_specs:
            raise SplitDecisionValidationError(f"缺少 {role} RoleSpec。")
        return WorkerAssignment(
            assignment_id=assignment_id,
            task_id=task_id,
            role=role,
            objective=objective,
            constraints=constraints,
            input_context=input_context,
            dependencies=dependencies,
            role_spec=self._role_specs[role],
        )

    @staticmethod
    def _assert_reassignable(current: WorkerRole, target: WorkerRole) -> None:
        if target not in _WORKER_ROLES or target == current:
            raise SplitDecisionValidationError(
                "reassign_to 必须是不同的 Researcher/Coder/Tester 角色。"
            )


__all__ = [
    "CollaborationEvent",
    "CollaborationPlan",
    "CollaborationTrace",
    "Manager",
    "ManagerAction",
    "ManagerDecision",
    "RoleSpec",
    "TraceEventKind",
    "WorkerAssignment",
    "WorkerResult",
    "WorkerStatus",
    "default_role_specs",
]
