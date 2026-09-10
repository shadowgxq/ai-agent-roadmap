"""Recoverable progress contracts for W17 long-horizon execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

ProgressStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "failed",
]


class ProgressValidationError(ValueError):
    """Raised when a persisted progress snapshot is not self-consistent."""


def utc_now_iso() -> str:
    """Return a stable, timezone-aware timestamp for checkpoint fields."""

    return datetime.now(timezone.utc).isoformat()


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProgressValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProgressValidationError(f"{field_name} 必须是字符串数组。")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{field_name}[{index}]"))
    return tuple(result)


@dataclass(frozen=True)
class StepProgress:
    """Small, durable progress record for one plan step."""

    step_id: str
    status: ProgressStatus = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    evidence_refs: tuple[str, ...] = ()
    tool_call_ids: tuple[str, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _text(self.step_id, "step_id"))
        if self.status == "running":  # type: ignore[comparison-overlap]
            object.__setattr__(self, "status", "in_progress")
        if self.status not in (
            "pending",
            "in_progress",
            "completed",
            "blocked",
            "failed",
        ):
            raise ProgressValidationError("步骤 progress status 不合法。")
        for field_name, value in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if value is not None:
                object.__setattr__(self, field_name, _text(value, field_name))
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(_text(value, "evidence_refs")
                  for value in self.evidence_refs),
        )
        object.__setattr__(
            self,
            "tool_call_ids",
            tuple(_text(value, "tool_call_ids")
                  for value in self.tool_call_ids),
        )
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _text(self.failure_reason, "failure_reason"),
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StepProgress:
        status = payload.get("status", "pending")
        if not isinstance(status, str):
            raise ProgressValidationError("步骤 progress status 必须是字符串。")
        return cls(
            step_id=_text(payload.get("step_id"), "step_id"),
            status=status,  # type: ignore[arg-type]
            started_at=payload.get("started_at"),  # type: ignore[arg-type]
            completed_at=payload.get("completed_at"),  # type: ignore[arg-type]
            evidence_refs=_texts(payload.get(
                "evidence_refs", []), "evidence_refs"),
            tool_call_ids=_texts(payload.get(
                "tool_call_ids", []), "tool_call_ids"),
            # type: ignore[arg-type]
            failure_reason=payload.get("failure_reason"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "evidence_refs": list(self.evidence_refs),
            "tool_call_ids": list(self.tool_call_ids),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ProgressSnapshot:
    """Human/query-facing summary of a checkpointed execution."""

    goal_id: str | None
    goal_version: int | None
    plan_version: int | None
    status: ProgressStatus = "pending"
    current_step: str | None = None
    completed_steps: tuple[str, ...] = ()
    in_progress_step: str | None = None
    blocked_reason: str | None = None
    failed_steps: tuple[str, ...] = ()
    remaining_budget: Mapping[str, object] = field(default_factory=dict)
    step_progress: tuple[StepProgress, ...] = ()
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.goal_id is not None:
            object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if self.goal_version is not None and (
            not isinstance(self.goal_version, int)
            or isinstance(self.goal_version, bool)
            or self.goal_version <= 0
        ):
            raise ProgressValidationError("goal_version 必须是正整数或 null。")
        if self.plan_version is not None and (
            not isinstance(self.plan_version, int)
            or isinstance(self.plan_version, bool)
            or self.plan_version <= 0
        ):
            raise ProgressValidationError("plan_version 必须是正整数或 null。")
        if self.status == "running":  # type: ignore[comparison-overlap]
            object.__setattr__(self, "status", "in_progress")
        if self.status not in (
            "pending",
            "in_progress",
            "completed",
            "blocked",
            "failed",
        ):
            raise ProgressValidationError("progress snapshot status 不合法。")
        if self.current_step is not None:
            object.__setattr__(self, "current_step", _text(
                self.current_step, "current_step"))
        if self.in_progress_step is not None:
            object.__setattr__(
                self,
                "in_progress_step",
                _text(self.in_progress_step, "in_progress_step"),
            )
        if self.blocked_reason is not None:
            object.__setattr__(
                self,
                "blocked_reason",
                _text(self.blocked_reason, "blocked_reason"),
            )
        object.__setattr__(
            self,
            "completed_steps",
            tuple(_text(value, "completed_steps")
                  for value in self.completed_steps),
        )
        object.__setattr__(
            self,
            "failed_steps",
            tuple(_text(value, "failed_steps") for value in self.failed_steps),
        )
        object.__setattr__(self, "remaining_budget",
                           dict(self.remaining_budget))
        if any(not isinstance(item, StepProgress) for item in self.step_progress):
            raise ProgressValidationError("step_progress 只能包含 StepProgress。")
        object.__setattr__(self, "step_progress", tuple(self.step_progress))
        object.__setattr__(self, "updated_at", _text(
            self.updated_at, "updated_at"))

    @classmethod
    def empty(
        cls,
        *,
        goal_id: str | None,
        goal_version: int | None,
        remaining_budget: Mapping[str, object] | None = None,
    ) -> ProgressSnapshot:
        return cls(
            goal_id=goal_id,
            goal_version=goal_version,
            plan_version=None,
            remaining_budget=remaining_budget or {},
        )

    @property
    def completed_step_ids(self) -> tuple[str, ...]:
        """Compatibility name for callers that use the execution-state term."""

        return self.completed_steps

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ProgressSnapshot:
        raw_steps = payload.get("step_progress", payload.get("steps", []))
        if not isinstance(raw_steps, list):
            raise ProgressValidationError("step_progress 必须是数组。")
        step_progress: list[StepProgress] = []
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, Mapping):
                raise ProgressValidationError(f"step_progress[{index}] 必须是对象。")
            step_progress.append(StepProgress.from_dict(raw_step))
        completed_steps = _texts(
            payload.get("completed_steps", payload.get(
                "completed_step_ids", [])),
            "completed_steps",
        )
        failed_steps = _texts(payload.get("failed_steps", []), "failed_steps")
        remaining_budget = payload.get("remaining_budget", {})
        if not isinstance(remaining_budget, Mapping):
            raise ProgressValidationError("remaining_budget 必须是对象。")
        return cls(
            goal_id=payload.get("goal_id"),  # type: ignore[arg-type]
            goal_version=payload.get("goal_version"),  # type: ignore[arg-type]
            plan_version=payload.get("plan_version"),  # type: ignore[arg-type]
            status=payload.get("status", "pending"),  # type: ignore[arg-type]
            current_step=payload.get("current_step"),  # type: ignore[arg-type]
            completed_steps=completed_steps,
            in_progress_step=payload.get(
                "in_progress_step"),  # type: ignore[arg-type]
            # type: ignore[arg-type]
            blocked_reason=payload.get("blocked_reason"),
            failed_steps=failed_steps,
            remaining_budget=remaining_budget,
            step_progress=tuple(step_progress),
            # type: ignore[arg-type]
            updated_at=payload.get("updated_at", utc_now_iso()),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "goal_version": self.goal_version,
            "plan_version": self.plan_version,
            "status": self.status,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "completed_step_ids": list(self.completed_steps),
            "in_progress_step": self.in_progress_step,
            "blocked_reason": self.blocked_reason,
            "failed_steps": list(self.failed_steps),
            "remaining_budget": dict(self.remaining_budget),
            "step_progress": [item.as_dict() for item in self.step_progress],
            "updated_at": self.updated_at,
        }


__all__ = [
    "ProgressSnapshot",
    "ProgressStatus",
    "ProgressValidationError",
    "StepProgress",
    "utc_now_iso",
]
