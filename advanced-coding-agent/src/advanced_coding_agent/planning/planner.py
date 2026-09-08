"""Deterministic and LLM-backed structured Planners for W16 Session 2."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from ..classification import TaskClassification, classify_task
from ..contracts import TaskCase
from .model import PlannerModelResponse, StructuredPlanModel
from .plan import AgentPlan, PlanStep, PlanValidationError


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
    observations: tuple[str, ...] = ()

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
        object.__setattr__(
            self,
            "observations",
            _normalize_context(self.observations, "observations"),
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
                "observations": list(self.request.observations),
            },
            "classification": self.classification.as_dict(),
            "plan": self.plan.as_dict() if self.plan is not None else None,
        }


class Planner(Protocol):
    """Common interface implemented by deterministic and LLM planners."""

    def plan(self, request: PlanningRequest) -> PlanningResult:
        """Create a structured plan or explicitly skip planning."""

    def plan_cases(self, cases: Iterable[TaskCase]) -> PlanningBatchResult:
        """Plan a batch of fixed cases through the same planner boundary."""


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


def _plan_cases(
    planner: Planner,
    cases: Iterable[TaskCase],
) -> PlanningBatchResult:
    case_results = tuple(
        PlanningCaseResult(
            case=case,
            result=planner.plan(
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
        return _plan_cases(self, cases)

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


class PlannerOutputError(ValueError):
    """Raised when an LLM response is not a safe structured AgentPlan."""


class LLMPlanner:
    """Generate a plan with an LLM, then enforce the plan contract in code."""

    def __init__(
        self,
        model: StructuredPlanModel,
        *,
        max_steps: int = 8,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps 必须大于 0。")
        self._model = model
        self._max_steps = max_steps

    def plan(self, request: PlanningRequest) -> PlanningResult:
        classification = classify_task(request.goal)
        if not classification.planning_recommended:
            return PlanningResult(
                request=request,
                classification=classification,
                decision="skipped",
                reason="任务主要是一次只读或解释动作，跳过 Planning。",
            )

        response = self._model.complete(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(request),
        )
        try:
            candidate = AgentPlan.from_dict(self._parse_response(response))
        except PlanValidationError as exc:
            raise PlannerOutputError(
                f"LLM Planner 输出未通过 Plan 校验：{exc}"
            ) from exc
        self._validate_candidate(candidate, request)
        plan = AgentPlan(
            goal=request.goal,
            constraints=request.constraints,
            available_tools=request.available_tools,
            steps=candidate.steps,
            version=1,
        )
        return PlanningResult(
            request=request,
            classification=classification,
            decision="planned",
            reason="LLM 根据任务输入生成结构化计划，代码已完成契约校验。",
            plan=plan,
        )

    def plan_cases(self, cases: Iterable[TaskCase]) -> PlanningBatchResult:
        return _plan_cases(self, cases)

    def _system_prompt(self) -> str:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["goal", "constraints", "available_tools", "steps", "version"],
            "properties": {
                "goal": {"type": "string"},
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "available_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "version": {"type": "integer", "const": 1},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": self._max_steps,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "id",
                            "description",
                            "completion_criteria",
                            "dependencies",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "completion_criteria": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                            "dependencies": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
        return (
            "你是 coding agent 的 Planner，只负责把复杂目标拆解成最小可执行步骤。"
            "不要调用工具，不要修改文件，不要声称任何步骤已经完成。"
            "每个步骤必须有稳定 id、可观察的 completion_criteria 和依赖。"
            "只输出一个 JSON 对象，不要输出 Markdown 或解释文字。"
            f"输出必须符合以下 schema：{json.dumps(schema, ensure_ascii=False)}"
        )

    @staticmethod
    def _user_prompt(request: PlanningRequest) -> str:
        payload = {
            "goal": request.goal,
            "constraints": list(request.constraints),
            "available_tools": list(request.available_tools),
            "observations": list(request.observations),
        }
        return "请为以下任务生成结构化 AgentPlan：\n" + json.dumps(
            payload,
            ensure_ascii=False,
        )

    @staticmethod
    def _parse_response(response: PlannerModelResponse) -> Mapping[str, object]:
        if isinstance(response, Mapping):
            return response
        if not isinstance(response, str):
            raise PlannerOutputError("LLM Planner 返回值必须是 JSON 对象或 JSON 字符串。")
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise PlannerOutputError("LLM Planner 返回的内容不是合法 JSON。") from exc
        if not isinstance(payload, Mapping):
            raise PlannerOutputError("LLM Planner 返回的 JSON 顶层必须是对象。")
        return payload

    def _validate_candidate(
        self,
        candidate: AgentPlan,
        request: PlanningRequest,
    ) -> None:
        if candidate.goal != request.goal:
            raise PlannerOutputError("LLM Planner 不能修改原始 goal。")
        if candidate.version != 1:
            raise PlannerOutputError("初次规划的 version 必须为 1。")
        if len(candidate.steps) > self._max_steps:
            raise PlannerOutputError(
                f"LLM Planner 生成了 {len(candidate.steps)} 个步骤，超过上限 {self._max_steps}。"
            )
        if any(step.status != "pending" for step in candidate.steps):
            raise PlannerOutputError("初次规划的所有步骤必须是 pending。")
        if any(step.evidence_refs for step in candidate.steps):
            raise PlannerOutputError("初次规划不能伪造 evidence_refs。")
