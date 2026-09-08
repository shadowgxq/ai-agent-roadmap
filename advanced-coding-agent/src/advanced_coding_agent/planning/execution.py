"""Plan state and single-step execution for W16 Session 3."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from ..verification import VerificationResult, VerificationStatus
from .plan import AgentPlan, PlanStep, PlanValidationError

ExecutionStatus = Literal["pending", "running", "completed", "failed"]
StepExecutionStatus = Literal["running", "completed", "failed"]


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

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ExecutionStateError("步骤 summary 不能为空。")
        if not self.evidence_refs:
            raise ExecutionStateError("步骤结果必须包含至少一个 evidence reference。")


@dataclass(frozen=True)
class StepResult:
    """Persisted summary for one plan step, not the full tool output."""

    step_id: str
    status: StepExecutionStatus
    summary: str
    evidence_refs: tuple[str, ...] = ()
    verification_status: VerificationStatus | None = None
    verification_summary: str | None = None

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ExecutionStateError("step_id 不能为空。")
        if self.status not in ("running", "completed", "failed"):
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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StepResult:
        status = payload.get("status")
        if not isinstance(status, str):
            raise ExecutionStateError("步骤结果 status 必须是字符串。")
        return cls(
            step_id=_required_text(payload, "step_id"),
            status=status,  # type: ignore[arg-type]
            summary=_required_text(payload, "summary"),
            evidence_refs=_text_refs(payload.get("evidence_refs", []), "evidence_refs"),
            verification_status=payload.get("verification_status"),  # type: ignore[arg-type]
            verification_summary=payload.get("verification_summary"),  # type: ignore[arg-type]
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "verification_status": self.verification_status,
            "verification_summary": self.verification_summary,
        }


@dataclass
class PlanExecutionState:
    """Checkpointable execution state for one validated AgentPlan."""

    plan: AgentPlan
    current_step: str | None = None
    step_results: dict[str, StepResult] = field(default_factory=dict)
    status: ExecutionStatus = "pending"

    def __post_init__(self) -> None:
        if self.status not in ("pending", "running", "completed", "failed"):
            raise ExecutionStateError("execution status 不合法。")
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

    def claim_next_step(self) -> PlanStep | None:
        """Claim one runnable step, or resume the checkpointed running step."""

        if self.status in ("completed", "failed"):
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
            if all(dependency in completed for dependency in step.dependencies):
                self.current_step = step.id
                self.status = "running"
                self.step_results[step.id] = StepResult(
                    step_id=step.id,
                    status="running",
                    summary=f"已领取步骤：{step.description}",
                )
                self.plan = _update_plan_step(self.plan, step.id, "running")
                return step

        if len(completed) == len(self.plan.steps):
            self.status = "completed"
            return None
        raise ExecutionStateError("当前没有满足依赖的可执行步骤。")

    def record_step_result(
        self,
        step_id: str,
        *,
        status: Literal["completed", "failed"],
        summary: str,
        evidence_refs: Iterable[str],
        verification_status: VerificationStatus | None = None,
        verification_summary: str | None = None,
    ) -> None:
        """Record one step outcome and let code advance the state."""

        if self.current_step != step_id:
            raise ExecutionStateError(
                f"只能记录当前步骤 {self.current_step}，不能记录 {step_id}。"
            )
        result = StepResult(
            step_id=step_id,
            status=status,
            summary=summary,
            evidence_refs=tuple(evidence_refs),
            verification_status=verification_status,
            verification_summary=verification_summary,
        )
        self.step_results[step_id] = result
        self.plan = _update_plan_step(
            self.plan,
            step_id,
            status,
            evidence_refs=result.evidence_refs,
        )
        self.current_step = None
        self.status = "failed" if status == "failed" else "pending"
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
                raise ExecutionStateError(f"step_results[{index}] 必须是 JSON 对象。")
            result = StepResult.from_dict(raw_result)
            if result.step_id in results:
                raise ExecutionStateError(f"step_results 不能重复：{result.step_id}。")
            results[result.step_id] = result
        current_step = payload.get("current_step")
        if current_step is not None and not isinstance(current_step, str):
            raise ExecutionStateError("current_step 必须是字符串或 null。")
        status = payload.get("status", "pending")
        if not isinstance(status, str):
            raise ExecutionStateError("status 必须是字符串。")
        return cls(
            plan=plan,
            current_step=current_step,
            step_results=results,
            status=status,  # type: ignore[arg-type]
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
            )
            return None

        if self._verifier is None:
            state.record_step_result(
                step.id,
                status="completed",
                summary=execution.summary,
                evidence_refs=execution.evidence_refs,
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
            )
        else:
            state.record_step_result(
                step.id,
                status="failed",
                summary=f"{execution.summary}；验证未通过。",
                evidence_refs=evidence_refs or (f"verification:{step.id}",),
                verification_status=verification.status,
                verification_summary=verification.summary,
            )
        return execution

    def run_until_finished(self, state: PlanExecutionState) -> PlanExecutionState:
        """Convenience loop for the deterministic Session 3 demonstration."""

        while state.status not in ("completed", "failed"):
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
    status: Literal["running", "completed", "failed"],
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
    )
