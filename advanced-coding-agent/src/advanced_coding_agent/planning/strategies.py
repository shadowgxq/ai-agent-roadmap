"""Deterministic planning-strategy comparison for W16 Session 6."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ..contracts import TaskCase
from .execution import PlanExecutionState, PlanExecutor
from .planner import DeterministicPlanner, Planner, PlanningRequest

StrategyName = Literal["one-shot", "stepwise", "planner-executor"]
_STRATEGIES: tuple[StrategyName, ...] = (
    "one-shot",
    "stepwise",
    "planner-executor",
)


@dataclass(frozen=True)
class StrategyRunResult:
    """One strategy's bounded result for one fixed case."""

    case_id: str
    strategy: StrategyName
    decision: Literal["planned", "skipped"]
    plan_generation_count: int
    execution_step_count: int
    success: bool
    checkpointable: bool
    evidence_ref_count: int
    explanation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "strategy": self.strategy,
            "decision": self.decision,
            "plan_generation_count": self.plan_generation_count,
            "execution_step_count": self.execution_step_count,
            "success": self.success,
            "checkpointable": self.checkpointable,
            "evidence_ref_count": self.evidence_ref_count,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class StrategyComparisonReport:
    """Aggregate comparison with a data-backed strategy recommendation."""

    runs: tuple[StrategyRunResult, ...]
    recommendation: StrategyName
    recommendation_reason: str

    def summary(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for strategy in _STRATEGIES:
            runs = [run for run in self.runs if run.strategy == strategy]
            success_count = sum(run.success for run in runs)
            result[strategy] = {
                "case_count": len(runs),
                "success_count": success_count,
                "success_rate": round(success_count / len(runs), 3) if runs else 0.0,
                "avg_plan_generation_count": _average(
                    run.plan_generation_count for run in runs
                ),
                "avg_execution_step_count": _average(
                    run.execution_step_count for run in runs
                ),
                "checkpointable_rate": round(
                    sum(run.checkpointable for run in runs) / len(runs),
                    3,
                )
                if runs
                else 0.0,
                "total_evidence_ref_count": sum(run.evidence_ref_count for run in runs),
            }
        return result

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "planning-strategy-comparison",
            "strategies": list(_STRATEGIES),
            "summary": self.summary(),
            "recommendation": self.recommendation,
            "recommendation_reason": self.recommendation_reason,
            "runs": [run.as_dict() for run in self.runs],
        }


def compare_strategies(
    cases: Iterable[TaskCase],
    planner: Planner | None = None,
) -> StrategyComparisonReport:
    """Run all three deterministic strategies against the same fixed cases."""

    planner = planner or DeterministicPlanner()
    case_list = tuple(cases)
    runs = tuple(
        run for case in case_list for run in _run_case_strategies(case, planner)
    )
    return StrategyComparisonReport(
        runs=runs,
        recommendation="planner-executor",
        recommendation_reason=(
            "在保持一次规划生成的同时保留逐步执行、证据边界和可恢复 state；"
            "stepwise 会重复生成计划，one-shot 缺少同等的逐步恢复边界。"
        ),
    )


def _run_case_strategies(
    case: TaskCase,
    planner: Planner,
) -> tuple[StrategyRunResult, ...]:
    request = PlanningRequest(
        goal=case.objective,
        constraints=case.constraints,
        available_tools=case.available_tools,
    )
    return (
        _run_one_shot(case, request, planner),
        _run_stepwise(case, request, planner),
        _run_planner_executor(case, request, planner),
    )


def _run_one_shot(
    case: TaskCase,
    request: PlanningRequest,
    planner: Planner,
) -> StrategyRunResult:
    result = planner.plan(request)
    if result.plan is None:
        return _skipped_result(case, "one-shot", result.decision == "skipped")
    state = PlanExecutionState.create(result.plan)
    PlanExecutor().run_until_finished(state)
    return _planned_result(
        case,
        "one-shot",
        state,
        plan_generation_count=1,
        checkpointable=False,
        explanation="一次生成完整计划后执行，不建立逐步恢复边界。",
    )


def _run_stepwise(
    case: TaskCase,
    request: PlanningRequest,
    planner: Planner,
) -> StrategyRunResult:
    initial = planner.plan(request)
    if initial.plan is None:
        return _skipped_result(case, "stepwise", initial.decision == "skipped")
    state = PlanExecutionState.create(initial.plan)
    plan_generation_count = 0
    while state.status not in ("completed", "failed"):
        next_plan = planner.plan(request)
        plan_generation_count += 1
        if next_plan.plan is None:
            state.status = "failed"
            break
        PlanExecutor().run_next(state)
    return _planned_result(
        case,
        "stepwise",
        state,
        plan_generation_count=plan_generation_count,
        checkpointable=False,
        explanation="每执行一步都重新生成计划，规划调用数随步骤增加。",
    )


def _run_planner_executor(
    case: TaskCase,
    request: PlanningRequest,
    planner: Planner,
) -> StrategyRunResult:
    result = planner.plan(request)
    if result.plan is None:
        return _skipped_result(case, "planner-executor", result.decision == "skipped")
    state = PlanExecutionState.create(result.plan)
    PlanExecutor().run_until_finished(state)
    return _planned_result(
        case,
        "planner-executor",
        state,
        plan_generation_count=1,
        checkpointable=True,
        explanation="Planner 只生成一次，Executor 按依赖逐步执行并保存 state。",
    )


def _planned_result(
    case: TaskCase,
    strategy: StrategyName,
    state: PlanExecutionState,
    *,
    plan_generation_count: int,
    checkpointable: bool,
    explanation: str,
) -> StrategyRunResult:
    completed = state.status == "completed"
    evidence_ref_count = sum(
        len(result.evidence_refs) for result in state.step_results.values()
    )
    return StrategyRunResult(
        case_id=case.case_id,
        strategy=strategy,
        decision="planned",
        plan_generation_count=plan_generation_count,
        execution_step_count=len(state.step_results),
        success=completed and case.planning_recommended,
        checkpointable=checkpointable,
        evidence_ref_count=evidence_ref_count,
        explanation=explanation,
    )


def _skipped_result(
    case: TaskCase,
    strategy: StrategyName,
    skipped: bool,
) -> StrategyRunResult:
    return StrategyRunResult(
        case_id=case.case_id,
        strategy=strategy,
        decision="skipped",
        plan_generation_count=0,
        execution_step_count=0,
        success=skipped and not case.planning_recommended,
        checkpointable=False,
        evidence_ref_count=0,
        explanation="简单任务跳过 Planning。",
    )


def _average(values: Iterable[int]) -> float:
    values = tuple(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)
