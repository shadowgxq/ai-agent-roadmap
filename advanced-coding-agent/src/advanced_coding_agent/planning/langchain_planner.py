"""LangChain structured-output Planner used by the LangGraph runtime."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from ..classification import classify_task
from ..contracts import TaskCase
from .plan import AgentPlan, PlanStep, PlanValidationError
from .planner import (
    PlanningBatchResult,
    PlanningCaseResult,
    PlanningRequest,
    PlanningResult,
    PlannerOutputError,
)


class StructuredPlanStep(BaseModel):
    """Provider-facing schema for one LLM-generated plan step."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    completion_criteria: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)


class StructuredAgentPlan(BaseModel):
    """Provider-facing structured output for an initial or revised plan."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    steps: list[StructuredPlanStep] = Field(min_length=1, max_length=8)
    version: Literal[1] = 1


PLANNER_SYSTEM_PROMPT = """你是 coding agent 的 Planner，只负责生成任务计划。

规则：
- 只拆解任务，不调用工具，不修改文件，不执行测试。
- 每个步骤必须有稳定 id、明确 description、可观察的 completion_criteria。
- 通过 dependencies 表达执行顺序，避免循环依赖。
- 只输出结构化 AgentPlan，不要声称任何步骤已经完成。
- 计划最多包含 8 个步骤。
"""


class LangChainPlanner:
    """Generate validated domain plans through LangChain structured output."""

    def __init__(self, model: BaseChatModel) -> None:
        self._structured_model = model.with_structured_output(
            StructuredAgentPlan,
            method="function_calling",
        )

    def plan(self, request: PlanningRequest) -> PlanningResult:
        classification = classify_task(request.goal)
        if not classification.planning_recommended:
            return PlanningResult(
                request=request,
                classification=classification,
                decision="skipped",
                reason="任务主要是一次只读或解释动作，跳过 Planning。",
            )

        response = self._structured_model.invoke(
            [
                SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=self._build_user_prompt(request)),
            ]
        )
        output = self._coerce_output(response)
        if output.goal != request.goal:
            raise PlannerOutputError("LangChain Planner 不能修改原始 goal。")
        if output.version != 1:
            raise PlannerOutputError("初次规划的 version 必须为 1。")
        try:
            plan = AgentPlan(
                goal=request.goal,
                constraints=request.constraints,
                available_tools=request.available_tools,
                steps=tuple(
                    PlanStep(
                        id=step.id,
                        description=step.description,
                        completion_criteria=tuple(step.completion_criteria),
                        dependencies=tuple(step.dependencies),
                    )
                    for step in output.steps
                ),
                version=1,
            )
        except PlanValidationError as exc:
            raise PlannerOutputError(
                f"LangChain Planner 输出未通过 Plan 校验：{exc}"
            ) from exc

        return PlanningResult(
            request=request,
            classification=classification,
            decision="planned",
            reason="LangChain structured output 生成计划，代码已完成契约校验。",
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
    def _build_user_prompt(request: PlanningRequest) -> str:
        return "请为以下任务生成 AgentPlan：\n" + json.dumps(
            {
                "goal": request.goal,
                "constraints": list(request.constraints),
                "available_tools": list(request.available_tools),
                "observations": list(request.observations),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _coerce_output(response: object) -> StructuredAgentPlan:
        if isinstance(response, StructuredAgentPlan):
            return response
        if isinstance(response, Mapping):
            try:
                return StructuredAgentPlan.model_validate(response)
            except ValueError as exc:
                raise PlannerOutputError(
                    f"LangChain Planner structured output 无效：{exc}"
                ) from exc
        raise PlannerOutputError("LangChain Planner 没有返回结构化 AgentPlan。")
