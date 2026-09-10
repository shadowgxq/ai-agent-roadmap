"""Persistent Goal and run-projection contracts for W17 Session 1.

The goal is the durable execution contract.  It deliberately contains no
conversation messages: messages can be compacted, while this contract must be
serializable and sufficient to continue a run with the current plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

SuccessCriterionKind = Literal[
    "command",
    "content_contains",
    "manual",
    "path_changed",
    "path_exists",
]
GoalRunStatus = Literal["pending", "running", "completed", "failed", "blocked"]


class GoalValidationError(ValueError):
    """Raised when a persistent Goal or its verifier criteria is malformed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoalValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise GoalValidationError(f"{field_name} 必须是字符串数组。")
    normalized: list[str] = []
    for index, item in enumerate(value):
        normalized.append(_text(item, f"{field_name}[{index}]"))
    return tuple(normalized)


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


@dataclass(frozen=True)
class SuccessCriterion:
    """One observable condition that a future verifier can execute."""

    id: str
    kind: SuccessCriterionKind
    description: str
    path: str | None = None
    command: tuple[str, ...] = ()
    expected_text: str | None = None

    def __post_init__(self) -> None:
        criterion_id = _text(self.id, "success_criterion.id")
        description = _text(
            self.description,
            f"criterion[{criterion_id}].description",
        )
        if self.kind not in (
            "command",
            "content_contains",
            "manual",
            "path_changed",
            "path_exists",
        ):
            raise GoalValidationError(f"criterion[{criterion_id}].kind 不合法。")

        path = _optional_text(self.path, f"criterion[{criterion_id}].path")
        expected_text = _optional_text(
            self.expected_text,
            f"criterion[{criterion_id}].expected_text",
        )
        command = _texts(self.command, f"criterion[{criterion_id}].command")

        if (
            self.kind in ("path_changed", "path_exists", "content_contains")
            and path is None
        ):
            raise GoalValidationError(
                f"criterion[{criterion_id}] 的 {self.kind} 检查必须提供 path。"
            )
        if self.kind == "content_contains" and expected_text is None:
            raise GoalValidationError(
                f"criterion[{criterion_id}] 的 content_contains 检查必须提供 "
                "expected_text。"
            )
        if self.kind == "command" and not command:
            raise GoalValidationError(
                f"criterion[{criterion_id}] 的 command 检查必须提供 command。"
            )
        if self.kind != "content_contains":
            expected_text = None
        if self.kind != "command":
            command = ()
        if self.kind == "manual":
            path = None

        object.__setattr__(self, "id", criterion_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "expected_text", expected_text)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SuccessCriterion":
        """Rehydrate a criterion from checkpoint-safe JSON data."""

        if not isinstance(payload, Mapping):
            raise GoalValidationError("success_criteria 中的元素必须是对象。")
        raw_command = payload.get("command", ())
        if raw_command is None:
            raw_command = ()
        return cls(
            id=_text(payload.get("id"), "success_criterion.id"),
            kind=payload.get("kind", "manual"),  # type: ignore[arg-type]
            description=_text(
                payload.get("description"),
                "success_criterion.description",
            ),
            path=payload.get("path"),
            command=_texts(raw_command, "success_criterion.command"),
            expected_text=payload.get("expected_text"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "description": self.description,
            "path": self.path,
            "command": list(self.command),
            "expected_text": self.expected_text,
        }


@dataclass(frozen=True)
class Goal:
    """Versioned objective and completion contract for one long-running run."""

    objective: str
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[SuccessCriterion, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    version: int = 1
    goal_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        objective = _text(self.objective, "objective")
        constraints = _texts(self.constraints, "constraints")
        criteria = tuple(self.success_criteria)
        if not criteria:
            raise GoalValidationError("success_criteria 不能为空。")
        if any(not isinstance(item, SuccessCriterion) for item in criteria):
            raise GoalValidationError(
                "success_criteria 只能包含 SuccessCriterion。"
            )
        criterion_ids = [criterion.id for criterion in criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise GoalValidationError("success_criteria 的 id 必须唯一。")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise GoalValidationError("created_at 必须是非空 ISO 时间字符串。")
        try:
            datetime.fromisoformat(
                self.created_at.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise GoalValidationError("created_at 必须是 ISO 时间字符串。") from exc
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise GoalValidationError("version 必须是整数。")
        if self.version <= 0:
            raise GoalValidationError("version 必须大于 0。")
        goal_id = _text(self.goal_id, "goal_id")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "success_criteria", criteria)
        object.__setattr__(self, "created_at", self.created_at.strip())
        object.__setattr__(self, "goal_id", goal_id)

    @classmethod
    def create(
        cls,
        *,
        objective: str,
        constraints: Sequence[str] = (),
        success_criteria: Sequence[SuccessCriterion] = (),
        goal_id: str | None = None,
        created_at: str | None = None,
        version: int = 1,
    ) -> "Goal":
        """Create a normalized Goal, retaining an explicit manual fallback."""

        criteria = tuple(success_criteria)
        if not criteria:
            criteria = (
                SuccessCriterion(
                    id="manual-review",
                    kind="manual",
                    description="未提供可执行条件，需要人工复核完成标准。",
                ),
            )
        return cls(
            objective=objective,
            constraints=_texts(constraints, "constraints"),
            success_criteria=criteria,
            goal_id=goal_id or uuid4().hex,
            created_at=created_at or _utc_now(),
            version=version,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Goal":
        """Rehydrate a Goal without consulting conversation history."""

        if not isinstance(payload, Mapping):
            raise GoalValidationError("goal 必须是对象。")
        raw_criteria = payload.get("success_criteria", [])
        if isinstance(raw_criteria, (str, bytes)) or not isinstance(
            raw_criteria,
            Sequence,
        ):
            raise GoalValidationError("success_criteria 必须是对象数组。")
        criteria: list[SuccessCriterion] = []
        for index, raw_criterion in enumerate(raw_criteria):
            if not isinstance(raw_criterion, Mapping):
                raise GoalValidationError(
                    f"success_criteria[{index}] 必须是对象。"
                )
            criteria.append(SuccessCriterion.from_dict(raw_criterion))
        return cls(
            objective=_text(payload.get("objective"), "objective"),
            constraints=_texts(payload.get("constraints", ()), "constraints"),
            success_criteria=tuple(criteria),
            created_at=_text(payload.get("created_at"), "created_at"),
            version=payload.get("version", 1),  # type: ignore[arg-type]
            goal_id=_text(payload.get("goal_id"), "goal_id"),
        )

    def revise(
        self,
        *,
        objective: str | None = None,
        constraints: Sequence[str] | None = None,
        success_criteria: Sequence[SuccessCriterion] | None = None,
    ) -> "Goal":
        """Return the next immutable Goal version with the same identity."""

        return replace(
            self,
            objective=objective if objective is not None else self.objective,
            constraints=(
                _texts(constraints, "constraints")
                if constraints is not None
                else self.constraints
            ),
            success_criteria=(
                tuple(success_criteria)
                if success_criteria is not None
                else self.success_criteria
            ),
            version=self.version + 1,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "success_criteria": [
                criterion.as_dict() for criterion in self.success_criteria
            ],
            "created_at": self.created_at,
            "version": self.version,
        }


@dataclass(frozen=True)
class GoalRunProjection:
    """Small query-oriented view of a run; never stores chat history."""

    run_id: str
    goal_id: str
    goal_version: int
    objective_summary: str
    status: GoalRunStatus = "pending"
    plan_version: int | None = None
    updated_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        run_id = _text(self.run_id, "run_id")
        goal_id = _text(self.goal_id, "goal_id")
        objective_summary = _text(self.objective_summary, "objective_summary")
        if self.status not in (
            "pending",
            "running",
            "completed",
            "failed",
            "blocked",
        ):
            raise GoalValidationError("run projection status 不合法。")
        if (
            not isinstance(self.goal_version, int)
            or isinstance(self.goal_version, bool)
            or self.goal_version <= 0
        ):
            raise GoalValidationError("goal_version 必须是正整数。")
        if self.plan_version is not None and (
            not isinstance(self.plan_version, int)
            or isinstance(self.plan_version, bool)
            or self.plan_version <= 0
        ):
            raise GoalValidationError("plan_version 必须是正整数或 null。")
        if not isinstance(self.updated_at, str) or not self.updated_at.strip():
            raise GoalValidationError("updated_at 必须是非空 ISO 时间字符串。")
        try:
            datetime.fromisoformat(
                self.updated_at.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise GoalValidationError("updated_at 必须是 ISO 时间字符串。") from exc
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "goal_id", goal_id)
        object.__setattr__(self, "objective_summary", objective_summary)
        object.__setattr__(self, "updated_at", self.updated_at.strip())

    @classmethod
    def from_goal(
        cls,
        goal: Goal,
        *,
        run_id: str,
        status: GoalRunStatus = "pending",
        plan_version: int | None = None,
    ) -> "GoalRunProjection":
        return cls(
            run_id=run_id,
            goal_id=goal.goal_id,
            goal_version=goal.version,
            objective_summary=goal.objective,
            status=status,
            plan_version=plan_version,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GoalRunProjection":
        if not isinstance(payload, Mapping):
            raise GoalValidationError("run_projection 必须是对象。")
        return cls(
            run_id=_text(payload.get("run_id"), "run_id"),
            goal_id=_text(payload.get("goal_id"), "goal_id"),
            # type: ignore[arg-type]
            goal_version=payload.get("goal_version", 1),
            objective_summary=_text(
                payload.get("objective_summary"),
                "objective_summary",
            ),
            status=payload.get("status", "pending"),  # type: ignore[arg-type]
            plan_version=payload.get("plan_version"),  # type: ignore[arg-type]
            updated_at=_text(
                payload.get("updated_at", _utc_now()),
                "updated_at",
            ),
        )

    def with_status(
        self,
        status: GoalRunStatus,
        *,
        plan_version: int | None = None,
    ) -> "GoalRunProjection":
        return replace(
            self,
            status=status,
            plan_version=(
                plan_version if plan_version is not None else self.plan_version
            ),
            updated_at=_utc_now(),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "goal_version": self.goal_version,
            "objective_summary": self.objective_summary,
            "status": self.status,
            "plan_version": self.plan_version,
            "updated_at": self.updated_at,
        }
