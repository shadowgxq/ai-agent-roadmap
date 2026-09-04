"""Deterministic structured Planner for W16 Session 2."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ..classification import TaskClassification, classify_task
from ..contracts import TaskCase
from .plan import AgentPlan, PlanStep


PlanningDecision = Literal["planned", "skipped"]


def _normalize_context(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须只包含字符串。")
        value = value.strip()
        if value:
            normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True)
class PlanningRequest:
    """The explicit inputs accepted by a Planner."""

    goal: str
    constraints: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        goal = self.goal.strip()
        if not goal:
            raise ValueError("goal 不能为空。")
        object.__setattr__(self, "goal", goal)
        object.__setattr__(
            self,
            "constraints",
            _normalize_context(self.constraints, "constraints"),
        )
        object.__setattr__(
            self,
            "available_tools",
            _normalize_context(self.available_tools, "available_tools"),
        )


@dataclass(frozen=True)
class PlanningResult:
    """Planner decision plus an optional validated structured plan."""

    request: PlanningRequest
    classification: TaskClassification
    decision: PlanningDecision
    reason: str
    plan: AgentPlan | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason 不能为空。")
        if self.decision == "planned" and self.plan is None:
            raise ValueError("planned 结果必须包含 plan。")
        if self.decision == "skipped" and self.plan is not None:
            raise ValueError("skipped 结果不能包含 plan。")

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "request": {
                "goal": self.request.goal,
                "constraints": list(self.request.constraints),
                "available_tools": list(self.request.available_tools),
            },
            "classification": self.classification.as_dict(),
            "plan": self.plan.as_dict() if self.plan is not None else None,
        }


@dataclass(frozen=True)
class PlanningCaseResult:
    """One fixed case paired with the Planner decision."""

    case: TaskCase
    result: PlanningResult

    @property
    def matches_expectation(self) -> bool:
        should_plan = self.case.planning_recommended
        did_plan = self.result.decision == "planned"
        return should_plan == did_plan

    def as_dict(self) -> dict[str, object]:
        return {
            "case": self.case.as_dict(),
            "result": self.result.as_dict(),
            "matches_expectation": self.matches_expectation,
        }


@dataclass(frozen=True)
class PlanningBatchResult:
    """Aggregate report for the Session 2 fixed planning cases."""

    case_results: tuple[PlanningCaseResult, ...]

    @property
    def match_count(self) -> int:
        return sum(
            case_result.matches_expectation for case_result in self.case_results
        )

    @property
    def accuracy(self) -> float:
        if not self.case_results:
            return 0.0
        return round(self.match_count / len(self.case_results), 3)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "structured-planning",
            "case_count": len(self.case_results),
            "planned_case_count": sum(
                result.result.decision == "planned"
                for result in self.case_results
            ),
            "skipped_case_count": sum(
                result.result.decision == "skipped"
                for result in self.case_results
            ),
            "expectation_match_count": self.match_count,
            "expectation_accuracy": self.accuracy,
            "cases": [result.as_dict() for result in self.case_results],
        }


class DeterministicPlanner:
    """Create a validated four-step plan without making a model call."""

    def plan(self, request: PlanningRequest) -> PlanningResult:
        classification = classify_task(request.goal)
        if not classification.planning_recommended:
            return PlanningResult(
                request=request,
                classification=classification,
                decision="skipped",
                reason="任务主要是一次只读或解释动作，跳过 Planning。",
            )

        plan = AgentPlan(
            goal=request.goal,
            constraints=request.constraints,
            available_tools=request.available_tools,
            steps=self._build_steps(request.goal),
        )
        return PlanningResult(
            request=request,
            classification=classification,
            decision="planned",
            reason="任务包含调查、修改或验证等有依赖动作，生成结构化计划。",
            plan=plan,
        )

    def plan_cases(self, cases: Iterable[TaskCase]) -> PlanningBatchResult:
        case_results = tuple(
            PlanningCaseResult(
                case=case,
                result=self.plan(
                    PlanningRequest(
                        goal=case.objective,
                        constraints=case.constraints,
                        available_tools=case.available_tools,
                    )
                ),
            )
            for case in cases
        )
        return PlanningBatchResult(case_results=case_results)

    @staticmethod
    def _build_steps(goal: str) -> tuple[PlanStep, ...]:
        return (
            PlanStep(
                id="locate-entry",
                description=f"定位与目标“{goal}”直接相关的入口文件和触发路径。",
                completion_criteria=("找到入口文件并记录入口路径。",),
            ),
            PlanStep(
                id="inspect-call-chain",
                description="检查从入口到失败点或待修改点的调用链。",
                completion_criteria=("确认关键调用链并记录根因候选证据。",),
                dependencies=("locate-entry",),
            ),
            PlanStep(
                id="change-root-cause",
                description="依据调用链证据修改导致目标问题的根因。",
                completion_criteria=("完成最小必要修改且保留修改位置证据。",),
                dependencies=("inspect-call-chain",),
            ),
            PlanStep(
                id="run-verification",
                description="运行与目标行为相关的测试或确定性验证。",
                completion_criteria=("验证命令执行完成并记录通过或失败结果。",),
                dependencies=("change-root-cause",),
            ),
        )
