"""Plan state and single-step execution for W16 Session 3."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from ..long_horizon.progress import (
    ProgressSnapshot,
    StepProgress,
    utc_now_iso,
)
from ..verification import VerificationResult, VerificationStatus
from .plan import AgentPlan, PlanStep, PlanValidationError

ExecutionStatus = Literal[
    "pending",
    "running",
    "in_progress",
    "completed",
    "failed",
    "blocked",
]
StepExecutionStatus = Literal[
    "running",
    "in_progress",
    "completed",
    "failed",
    "blocked",
]


class ExecutionStateError(ValueError):
    """Raised when an executor receives an invalid or inconsistent state."""


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ExecutionStateError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _text_refs(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ExecutionStateError(f"{field_name} 必须是字符串数组。")
    refs: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ExecutionStateError(f"{field_name}[{index}] 必须是非空字符串。")
        refs.append(item.strip())
    return tuple(refs)


@dataclass(frozen=True)
class StepExecution:
    """Small result returned by one step runner."""

    summary: str
    evidence_refs: tuple[str, ...]
    tool_call_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ExecutionStateError("步骤 summary 不能为空。")
        if not self.evidence_refs:
            raise ExecutionStateError("步骤结果必须包含至少一个 evidence reference。")
        if any(not isinstance(item, str) or not item.strip() for item in self.tool_call_ids):
            raise ExecutionStateError("tool_call_ids 只能包含非空字符串。")


@dataclass(frozen=True)
class StepResult:
    """Persisted summary for one plan step, not the full tool output."""

    step_id: str
    status: StepExecutionStatus
    summary: str
    evidence_refs: tuple[str, ...] = ()
    verification_status: VerificationStatus | None = None
    verification_summary: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    tool_call_ids: tuple[str, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "in_progress":  # type: ignore[comparison-overlap]
            object.__setattr__(self, "status", "running")
        if not self.step_id.strip():
            raise ExecutionStateError("step_id 不能为空。")
        if self.status not in ("running", "completed", "failed", "blocked"):
            raise ExecutionStateError("步骤结果 status 不合法。")
        if not self.summary.strip():
            raise ExecutionStateError("步骤结果 summary 不能为空。")
        if self.status != "running" and not self.evidence_refs:
            raise ExecutionStateError(
                f"步骤 {self.step_id} 的最终结果必须包含 evidence reference。"
            )
        if self.verification_status not in (None, "pass", "fail", "needs_review"):
            raise ExecutionStateError("verification_status 不合法。")
        if self.verification_status is not None and (
            self.verification_summary is None or not self.verification_summary.strip()
        ):
            raise ExecutionStateError(
                "存在 verification_status 时必须保存 verification_summary。"
            )
        for field_name, value in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ExecutionStateError(f"{field_name} 必须是非空字符串或 null。")
        if any(not isinstance(item, str) or not item.strip() for item in self.tool_call_ids):
            raise ExecutionStateError("tool_call_ids 只能包含非空字符串。")
        if self.failure_reason is not None and (
            not isinstance(self.failure_reason,
                           str) or not self.failure_reason.strip()
        ):
            raise ExecutionStateError("failure_reason 必须是非空字符串或 null。")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StepResult:
        status = payload.get("status")
        if not isinstance(status, str):
            raise ExecutionStateError("步骤结果 status 必须是字符串。")
        if status == "in_progress":
            # W17 names the public progress state ``in_progress`` while W16
            # checkpoints used ``running``; normalize at the persistence edge.
            status = "running"
        return cls(
            step_id=_required_text(payload, "step_id"),
            status=status,  # type: ignore[arg-type]
            summary=_required_text(payload, "summary"),
            evidence_refs=_text_refs(payload.get(
                "evidence_refs", []), "evidence_refs"),
            verification_status=payload.get(
                "verification_status"),  # type: ignore[arg-type]
            verification_summary=payload.get(
                "verification_summary"),  # type: ignore[arg-type]
            started_at=payload.get("started_at"),  # type: ignore[arg-type]
            completed_at=payload.get("completed_at"),  # type: ignore[arg-type]
            tool_call_ids=_text_refs(
                payload.get("tool_call_ids", []), "tool_call_ids"
            ),
            # type: ignore[arg-type]
            failure_reason=payload.get("failure_reason"),
        )

    def to_progress(self) -> StepProgress:
        """Convert the legacy execution result into the W17 progress contract."""

        status = "in_progress" if self.status == "running" else self.status
        return StepProgress(
            step_id=self.step_id,
            status=status,  # type: ignore[arg-type]
            started_at=self.started_at,
            completed_at=self.completed_at,
            evidence_refs=self.evidence_refs,
            tool_call_ids=self.tool_call_ids,
            failure_reason=self.failure_reason,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "progress_status": "in_progress"
            if self.status == "running"
            else self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "verification_status": self.verification_status,
            "verification_summary": self.verification_summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "tool_call_ids": list(self.tool_call_ids),
            "failure_reason": self.failure_reason,
        }


@dataclass
class PlanExecutionState:
    """Checkpointable execution state for one validated AgentPlan."""

    plan: AgentPlan
    current_step: str | None = None
    step_results: dict[str, StepResult] = field(default_factory=dict)
    status: ExecutionStatus = "pending"
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "in_progress":  # type: ignore[comparison-overlap]
            self.status = "running"
        if self.status not in (
            "pending",
            "running",
            "completed",
            "failed",
            "blocked",
        ):
            raise ExecutionStateError("execution status 不合法。")
        if self.blocked_reason is not None and (
            not isinstance(self.blocked_reason, str)
            or not self.blocked_reason.strip()
        ):
            raise ExecutionStateError("blocked_reason 必须是非空字符串或 null。")
        if self.status == "blocked" and self.blocked_reason is None:
            raise ExecutionStateError("blocked 状态必须包含 blocked_reason。")
        known_ids = {step.id for step in self.plan.steps}
        unknown_results = set(self.step_results) - known_ids
        if unknown_results:
            raise ExecutionStateError(
                f"step_results 包含未知步骤：{', '.join(sorted(unknown_results))}。"
            )
        if self.current_step is not None and self.current_step not in known_ids:
            raise ExecutionStateError(f"current_step 不存在：{self.current_step}。")
        if self.current_step is not None:
            current_result = self.step_results.get(self.current_step)
            if current_result is None or current_result.status != "running":
                raise ExecutionStateError(
                    "current_step 必须对应一个 status=running 的步骤结果。"
                )

    @classmethod
    def create(cls, plan: AgentPlan) -> PlanExecutionState:
        plan.validate()
        return cls(plan=plan)

    @property
    def completed_step_ids(self) -> tuple[str, ...]:
        return tuple(
            step.id
            for step in self.plan.steps
            if self.step_results.get(step.id, None)
            and self.step_results[step.id].status == "completed"
        )

    @property
    def failed_step_ids(self) -> tuple[str, ...]:
        return tuple(
            step.id
            for step in self.plan.steps
            if self.step_results.get(step.id, None)
            and self.step_results[step.id].status == "failed"
        )

    def progress_snapshot(
        self,
        *,
        remaining_budget: Mapping[str, object] | None = None,
    ) -> ProgressSnapshot:
        """Project full execution state into the compact recovery summary."""

        step_progress = tuple(
            self.step_results[step.id].to_progress()
            if step.id in self.step_results
            else StepProgress(step_id=step.id)
            for step in self.plan.steps
        )
        return ProgressSnapshot(
            goal_id=self.plan.goal_id,
            goal_version=self.plan.goal_version,
            plan_version=self.plan.version,
            status=("in_progress" if self.status ==
                    "running" else self.status),
            current_step=self.current_step,
            completed_steps=self.completed_step_ids,
            in_progress_step=self.current_step if self.status == "running" else None,
            blocked_reason=self.blocked_reason,
            failed_steps=self.failed_step_ids,
            remaining_budget=remaining_budget or {},
            step_progress=step_progress,
        )

    def claim_next_step(self) -> PlanStep | None:
        """Claim one runnable step, or resume the checkpointed running step."""

        if self.status in ("completed", "failed", "blocked"):
            return None

        if self.current_step is not None:
            self.status = "running"
            return self._get_step(self.current_step)

        completed = set(self.completed_step_ids)
        for step in self.plan.steps:
            previous = self.step_results.get(step.id)
            if previous is not None and previous.status == "completed":
                continue
            if previous is not None and previous.status == "failed":
                self.status = "failed"
                return None
            if previous is not None and previous.status == "blocked":
                self.status = "blocked"
                self.blocked_reason = (
                    previous.failure_reason
                    or f"步骤 {step.id} 仍处于 blocked，等待外部解除阻塞。"
                )
                return None
            if all(dependency in completed for dependency in step.dependencies):
                self.current_step = step.id
                self.status = "running"
                self.blocked_reason = None
                self.step_results[step.id] = StepResult(
                    step_id=step.id,
                    status="running",
                    summary=f"已领取步骤：{step.description}",
                    started_at=utc_now_iso(),
                )
                self.plan = _update_plan_step(self.plan, step.id, "running")
                return step

        if len(completed) == len(self.plan.steps):
            self.status = "completed"
            return None
        self.status = "blocked"
        self.blocked_reason = "当前没有满足依赖的可执行步骤，等待依赖恢复或人工介入。"
        return None

    def resume_blocked_step(self, step_id: str | None = None) -> PlanStep:
        """Explicitly resume a blocked step without replaying completed steps."""

        if self.status != "blocked":
            raise ExecutionStateError("只有 blocked 状态才能显式恢复步骤。")
        candidates = [
            step.id
            for step in self.plan.steps
            if self.step_results.get(step.id, None)
            and self.step_results[step.id].status == "blocked"
        ]
        selected_id = step_id or (
            candidates[0] if len(candidates) == 1 else None)
        if selected_id is None:
            raise ExecutionStateError("blocked 状态没有唯一可恢复的步骤。")
        step = self._get_step(selected_id)
        previous = self.step_results.get(selected_id)
        if previous is None or previous.status != "blocked":
            raise ExecutionStateError(f"步骤 {selected_id} 不是 blocked 状态。")
        completed = set(self.completed_step_ids)
        if not all(dependency in completed for dependency in step.dependencies):
            raise ExecutionStateError(f"步骤 {selected_id} 的依赖尚未满足。")
        self.current_step = selected_id
        self.status = "running"
        self.blocked_reason = None
        self.step_results[selected_id] = StepResult(
            step_id=selected_id,
            status="running",
            summary=f"恢复步骤：{step.description}",
            started_at=previous.started_at or utc_now_iso(),
            tool_call_ids=previous.tool_call_ids,
        )
        self.plan = _update_plan_step(self.plan, selected_id, "running")
        return step

    def resume(self) -> PlanStep | None:
        """Clear a dependency/budget block and claim only a currently runnable step."""

        if self.status != "blocked":
            raise ExecutionStateError("只有 blocked 状态才能调用 resume。")
        if any(
            result.status == "blocked" for result in self.step_results.values()
        ):
            return self.resume_blocked_step()
        self.status = "pending"
        self.blocked_reason = None
        return self.claim_next_step()

    def record_step_result(
        self,
        step_id: str,
        *,
        status: Literal["completed", "failed", "blocked"],
        summary: str,
        evidence_refs: Iterable[str],
        verification_status: VerificationStatus | None = None,
        verification_summary: str | None = None,
        tool_call_ids: Iterable[str] = (),
        blocked_reason: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Record one step outcome and let code advance the state."""

        if self.current_step != step_id:
            raise ExecutionStateError(
                f"只能记录当前步骤 {self.current_step}，不能记录 {step_id}。"
            )
        previous = self.step_results.get(step_id)
        resolved_failure_reason = failure_reason or blocked_reason
        if status == "blocked" and not blocked_reason:
            raise ExecutionStateError("blocked 步骤必须包含 blocked_reason。")
        result = StepResult(
            step_id=step_id,
            status=status,
            summary=summary,
            evidence_refs=tuple(evidence_refs),
            verification_status=verification_status,
            verification_summary=verification_summary,
            started_at=previous.started_at if previous else utc_now_iso(),
            completed_at=utc_now_iso(),
            tool_call_ids=tuple(tool_call_ids),
            failure_reason=resolved_failure_reason,
        )
        self.step_results[step_id] = result
        self.plan = _update_plan_step(
            self.plan,
            step_id,
            status,
            evidence_refs=result.evidence_refs,
        )
        self.current_step = None
        self.blocked_reason = blocked_reason if status == "blocked" else None
        self.status = (
            "failed"
            if status == "failed"
            else "blocked"
            if status == "blocked"
            else "pending"
        )
        if status == "completed" and len(self.completed_step_ids) == len(
            self.plan.steps
        ):
            self.status = "completed"

    def as_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.as_dict(),
            "current_step": self.current_step,
            "step_results": [result.as_dict() for result in self.step_results.values()],
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "progress_snapshot": self.progress_snapshot().as_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PlanExecutionState:
        raw_plan = payload.get("plan")
        raw_results = payload.get("step_results", [])
        if not isinstance(raw_plan, Mapping):
            raise ExecutionStateError("plan 必须是 JSON 对象。")
        if not isinstance(raw_results, list):
            raise ExecutionStateError("step_results 必须是 JSON 数组。")
        try:
            plan = AgentPlan.from_dict(raw_plan)
        except PlanValidationError as exc:
            raise ExecutionStateError(f"plan 恢复失败：{exc}") from exc
        results: dict[str, StepResult] = {}
        for index, raw_result in enumerate(raw_results):
            if not isinstance(raw_result, Mapping):
                raise ExecutionStateError(
                    f"step_results[{index}] 必须是 JSON 对象。")
            result = StepResult.from_dict(raw_result)
            if result.step_id in results:
                raise ExecutionStateError(
                    f"step_results 不能重复：{result.step_id}。")
            results[result.step_id] = result
        current_step = payload.get("current_step")
        if current_step is not None and not isinstance(current_step, str):
            raise ExecutionStateError("current_step 必须是字符串或 null。")
        status = payload.get("status", "pending")
        if not isinstance(status, str):
            raise ExecutionStateError("status 必须是字符串。")
        if status == "in_progress":
            status = "running"
        blocked_reason = payload.get("blocked_reason")
        if status == "blocked" and blocked_reason is None:
            blocked_reason = "从旧 checkpoint 恢复的 blocked 状态，等待人工介入。"
        return cls(
            plan=plan,
            current_step=current_step,
            step_results=results,
            status=status,  # type: ignore[arg-type]
            blocked_reason=blocked_reason,  # type: ignore[arg-type]
        )

    def _get_step(self, step_id: str) -> PlanStep:
        for step in self.plan.steps:
            if step.id == step_id:
                return step
        raise ExecutionStateError(f"步骤不存在：{step_id}。")


StepRunner = Callable[[PlanStep, PlanExecutionState], StepExecution]
StepVerifier = Callable[[PlanStep, StepExecution], VerificationResult]


class PlanExecutor:
    """Execute at most one plan step per call."""

    def __init__(
        self,
        step_runner: StepRunner | None = None,
        verifier: StepVerifier | None = None,
    ) -> None:
        self._step_runner = step_runner or self._default_step_runner
        self._verifier = verifier

    def run_next(self, state: PlanExecutionState) -> StepExecution | None:
        """Claim, execute, and record one step; return None at a terminal state."""

        step = state.claim_next_step()
        if step is None:
            return None
        try:
            execution = self._step_runner(step, state)
        except Exception as exc:  # noqa: BLE001 - persist runner failure in state.
            state.record_step_result(
                step.id,
                status="failed",
                summary=f"步骤执行失败：{type(exc).__name__}: {exc}",
                evidence_refs=(f"runner-error:{step.id}",),
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
            return None

        if self._verifier is None:
            state.record_step_result(
                step.id,
                status="completed",
                summary=execution.summary,
                evidence_refs=execution.evidence_refs,
                tool_call_ids=execution.tool_call_ids,
            )
            return execution

        try:
            verification = self._verifier(step, execution)
        except Exception as exc:  # noqa: BLE001 - verifier failure needs recovery.
            state.record_step_result(
                step.id,
                status="failed",
                summary=f"验证器执行失败：{type(exc).__name__}: {exc}",
                evidence_refs=(f"verifier-error:{step.id}",),
                verification_status="needs_review",
                verification_summary="验证器本身发生异常，需要人工复核。",
                tool_call_ids=execution.tool_call_ids,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
            return execution

        evidence_refs = tuple(
            dict.fromkeys(execution.evidence_refs + verification.evidence_refs)
        )
        if verification.status == "pass":
            state.record_step_result(
                step.id,
                status="completed",
                summary=execution.summary,
                evidence_refs=evidence_refs,
                verification_status=verification.status,
                verification_summary=verification.summary,
                tool_call_ids=execution.tool_call_ids,
            )
        else:
            state.record_step_result(
                step.id,
                status="failed",
                summary=f"{execution.summary}；验证未通过。",
                evidence_refs=evidence_refs or (f"verification:{step.id}",),
                verification_status=verification.status,
                verification_summary=verification.summary,
                tool_call_ids=execution.tool_call_ids,
                failure_reason=verification.summary,
            )
        return execution

    def run_until_finished(self, state: PlanExecutionState) -> PlanExecutionState:
        """Convenience loop for the deterministic Session 3 demonstration."""

        while state.status not in ("completed", "failed", "blocked"):
            before = state.current_step
            self.run_next(state)
            if state.status == "running" and state.current_step == before:
                raise ExecutionStateError("Executor 未推进执行状态。")
        return state

    @staticmethod
    def _default_step_runner(
        step: PlanStep,
        _state: PlanExecutionState,
    ) -> StepExecution:
        return StepExecution(
            summary=f"已执行：{step.description}",
            evidence_refs=(f"step-result:{step.id}",),
        )


def _update_plan_step(
    plan: AgentPlan,
    step_id: str,
    status: Literal["running", "completed", "blocked", "failed"],
    *,
    evidence_refs: tuple[str, ...] = (),
) -> AgentPlan:
    """Update one step while preserving every other plan fact and version."""

    if step_id not in {step.id for step in plan.steps}:
        raise ExecutionStateError(f"不能更新不存在的步骤：{step_id}。")
    steps = tuple(
        replace(
            step,
            status=status if step.id == step_id else step.status,
            evidence_refs=evidence_refs
            if step.id == step_id and evidence_refs
            else step.evidence_refs,
        )
        for step in plan.steps
    )
    return AgentPlan(
        goal=plan.goal,
        steps=steps,
        version=plan.version,
        constraints=plan.constraints,
        available_tools=plan.available_tools,
        goal_id=plan.goal_id,
        goal_version=plan.goal_version,
    )
