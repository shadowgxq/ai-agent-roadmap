"""Serializable plan contracts and validation rules for W16-W17."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

PlanStepStatus = Literal["pending", "running", "completed", "failed"]
_VALID_STEP_STATUSES = frozenset({"pending", "running", "completed", "failed"})


class PlanValidationError(ValueError):
    """Raised when a structured plan cannot be safely executed later."""


def _normalize_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise PlanValidationError(f"{field_name} 必须是字符串。")
    normalized = value.strip()
    if not normalized:
        raise PlanValidationError(f"{field_name} 不能为空。")
    return normalized


def _normalize_texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise PlanValidationError(f"{field_name} 必须是字符串数组。")
    normalized: list[str] = []
    for index, item in enumerate(value):
        normalized.append(_normalize_text(item, f"{field_name}[{index}]"))
    return tuple(normalized)


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    if field_name not in payload:
        raise PlanValidationError(f"缺少字段 {field_name}。")
    return _normalize_text(payload[field_name], field_name)


@dataclass(frozen=True)
class PlanStep:
    """One executable unit in an explicit plan."""

    id: str
    description: str
    completion_criteria: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    status: PlanStepStatus = "pending"
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        step_id = _normalize_text(self.id, "step.id")
        description = _normalize_text(
            self.description,
            f"step[{step_id}].description",
        )
        completion_criteria = _normalize_texts(
            self.completion_criteria,
            f"step[{step_id}].completion_criteria",
        )
        if not completion_criteria:
            raise PlanValidationError(
                f"step[{step_id}].completion_criteria 不能为空。")
        dependencies = _normalize_texts(
            self.dependencies,
            f"step[{step_id}].dependencies",
        )
        evidence_refs = _normalize_texts(
            self.evidence_refs,
            f"step[{step_id}].evidence_refs",
        )
        if not isinstance(self.status, str) or self.status not in _VALID_STEP_STATUSES:
            raise PlanValidationError(
                f"step[{step_id}].status 必须是 {_VALID_STEP_STATUSES} 之一。"
            )
        if step_id in dependencies:
            raise PlanValidationError(f"步骤 {step_id} 不能依赖自己。")
        if len(set(dependencies)) != len(dependencies):
            raise PlanValidationError(f"步骤 {step_id} 的 dependencies 不能重复。")
        object.__setattr__(self, "id", step_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "completion_criteria", completion_criteria)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "evidence_refs", evidence_refs)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PlanStep:
        """Build one step from structured data and reject malformed fields."""

        return cls(
            id=_required_text(payload, "id"),
            description=_required_text(payload, "description"),
            completion_criteria=_normalize_texts(
                payload.get("completion_criteria", ()),
                "completion_criteria",
            ),
            dependencies=_normalize_texts(
                payload.get("dependencies", ()),
                "dependencies",
            ),
            status=payload.get("status", "pending"),  # type: ignore[arg-type]
            evidence_refs=_normalize_texts(
                payload.get("evidence_refs", ()),
                "evidence_refs",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "description": self.description,
            "completion_criteria": list(self.completion_criteria),
            "dependencies": list(self.dependencies),
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class AgentPlan:
    """Structured planning state that can be serialized and validated."""

    goal: str
    steps: tuple[PlanStep, ...]
    version: int = 1
    constraints: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    goal_id: str | None = None
    goal_version: int | None = None

    def __post_init__(self) -> None:
        goal = _normalize_text(self.goal, "goal")
        steps = tuple(self.steps)
        if not steps:
            raise PlanValidationError("steps 不能为空。")
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise PlanValidationError("version 必须是整数。")
        if self.version <= 0:
            raise PlanValidationError("version 必须大于 0。")
        constraints = _normalize_texts(self.constraints, "constraints")
        available_tools = _normalize_texts(
            self.available_tools, "available_tools")
        goal_id = (
            _normalize_text(self.goal_id, "goal_id")
            if self.goal_id is not None
            else None
        )
        if self.goal_version is not None and (
            not isinstance(self.goal_version, int)
            or isinstance(self.goal_version, bool)
            or self.goal_version <= 0
        ):
            raise PlanValidationError("goal_version 必须是正整数或 null。")
        if (goal_id is None) != (self.goal_version is None):
            raise PlanValidationError(
                "goal_id 和 goal_version 必须同时存在或同时为空。"
            )
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "available_tools", available_tools)
        object.__setattr__(self, "goal_id", goal_id)
        self.validate()

    def validate(self) -> AgentPlan:
        """Validate IDs, dependency references, and dependency cycles."""

        if any(not isinstance(step, PlanStep) for step in self.steps):
            raise PlanValidationError("steps 中只能包含 PlanStep。")

        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise PlanValidationError("steps 的 id 必须唯一。")
        known_ids = set(step_ids)
        for step in self.steps:
            missing = [
                dependency
                for dependency in step.dependencies
                if dependency not in known_ids
            ]
            if missing:
                raise PlanValidationError(
                    f"步骤 {step.id} 引用了不存在的依赖：{', '.join(missing)}。"
                )

        dependencies = {step.id: step.dependencies for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise PlanValidationError(f"计划依赖存在环：{step_id}。")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> AgentPlan:
        """Rehydrate a plan from structured data instead of Markdown text."""

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raise PlanValidationError("steps 必须是 JSON 数组。")
        steps: list[PlanStep] = []
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, Mapping):
                raise PlanValidationError(f"steps[{index}] 必须是 JSON 对象。")
            steps.append(PlanStep.from_dict(raw_step))
        return cls(
            goal=_required_text(payload, "goal"),
            steps=tuple(steps),
            version=payload.get("version", 1),  # type: ignore[arg-type]
            constraints=_normalize_texts(
                payload.get("constraints", ()),
                "constraints",
            ),
            available_tools=_normalize_texts(
                payload.get("available_tools", ()),
                "available_tools",
            ),
            goal_id=(
                _normalize_text(payload["goal_id"], "goal_id")
                if payload.get("goal_id") is not None
                else None
            ),
            goal_version=payload.get("goal_version"),  # type: ignore[arg-type]
        )

    def bind_goal(self, *, goal_id: str, goal_version: int) -> "AgentPlan":
        """Bind this plan to the immutable Goal version it is executing."""

        return AgentPlan(
            goal=self.goal,
            steps=self.steps,
            version=self.version,
            constraints=self.constraints,
            available_tools=self.available_tools,
            goal_id=goal_id,
            goal_version=goal_version,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "available_tools": list(self.available_tools),
            "steps": [step.as_dict() for step in self.steps],
            "version": self.version,
            "goal_id": self.goal_id,
            "goal_version": self.goal_version,
        }
