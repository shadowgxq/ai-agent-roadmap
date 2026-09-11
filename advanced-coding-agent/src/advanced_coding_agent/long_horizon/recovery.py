"""Bounded failure-recovery contracts for W17 Session 4."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

FailureKind = Literal[
    "tool_timeout",
    "tool_failure",
    "verification_failure",
    "plan_invalidated",
    "database_disconnect",
    "worker_restart",
    "unknown_external_result",
]
RecoveryAction = Literal[
    "retry",
    "replan",
    "reconcile",
    "resume_checkpoint",
    "blocked",
    "manual_review",
]
RecoverySourceKind = Literal["checkpoint", "run", "evidence"]

_FAILURE_KINDS = frozenset(
    {
        "tool_timeout",
        "tool_failure",
        "verification_failure",
        "plan_invalidated",
        "database_disconnect",
        "worker_restart",
        "unknown_external_result",
    }
)
_RECOVERY_ACTIONS = frozenset(
    {
        "retry",
        "replan",
        "reconcile",
        "resume_checkpoint",
        "blocked",
        "manual_review",
    }
)
_RECOVERY_SOURCE_KINDS = frozenset({"checkpoint", "run", "evidence"})


class RecoveryValidationError(ValueError):
    """Raised when a recovery event or checkpoint cannot be trusted."""


class RecoveryConsistencyError(RecoveryValidationError):
    """Raised when checkpoint, run, and evidence versions disagree."""


class RecoveryFailure(RuntimeError):
    """Base exception carrying the recovery classification for a failed call."""

    recovery_kind: FailureKind = "tool_failure"
    default_outcome_known = True
    default_external_side_effect = False

    def __init__(
        self,
        message: str,
        *,
        operation_key: str | None = None,
        evidence_refs: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.operation_key = operation_key
        self.evidence_refs = tuple(evidence_refs)


class ToolTimeoutError(RecoveryFailure):
    """A tool did not finish within its bounded timeout."""

    recovery_kind: FailureKind = "tool_timeout"


class DatabaseDisconnectedError(RecoveryFailure):
    """The database connection disappeared before the operation was confirmed."""

    recovery_kind: FailureKind = "database_disconnect"


class UnknownExternalResultError(RecoveryFailure):
    """An external side effect may have happened, but its result is unknown."""

    recovery_kind: FailureKind = "unknown_external_result"
    default_outcome_known = False
    default_external_side_effect = True


class PlanInvalidatedError(RecoveryFailure):
    """Evidence invalidated an assumption used by the current plan."""

    recovery_kind: FailureKind = "plan_invalidated"


class WorkerRestartError(RecoveryFailure):
    """A worker restarted and must resume from a durable checkpoint."""

    recovery_kind: FailureKind = "worker_restart"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RecoveryValidationError(f"{field_name} 必须是字符串数组。")
    return tuple(
        _text(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True)
class FailureEvent:
    """Normalized failure fact used by the recovery policy."""

    kind: FailureKind
    message: str
    step_id: str | None = None
    operation_key: str | None = None
    attempt: int = 1
    evidence_refs: tuple[str, ...] = ()
    outcome_known: bool = True
    external_side_effect: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _FAILURE_KINDS:
            raise RecoveryValidationError(f"failure kind 不合法：{self.kind}。")
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(
            self, "step_id", _optional_text(self.step_id, "step_id"))
        object.__setattr__(
            self,
            "operation_key",
            _optional_text(self.operation_key, "operation_key"),
        )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RecoveryValidationError("attempt 必须是正整数。")
        if not isinstance(self.outcome_known, bool):
            raise RecoveryValidationError("outcome_known 必须是布尔值。")
        if not isinstance(self.external_side_effect, bool):
            raise RecoveryValidationError("external_side_effect 必须是布尔值。")
        object.__setattr__(
            self,
            "evidence_refs",
            _texts(self.evidence_refs, "evidence_refs"),
        )
        if self.kind == "unknown_external_result":
            object.__setattr__(self, "outcome_known", False)
            object.__setattr__(self, "external_side_effect", True)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "message": self.message,
            "step_id": self.step_id,
            "operation_key": self.operation_key,
            "attempt": self.attempt,
            "evidence_refs": list(self.evidence_refs),
            "outcome_known": self.outcome_known,
            "external_side_effect": self.external_side_effect,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FailureEvent":
        kind = payload.get("kind", "tool_failure")
        if not isinstance(kind, str):
            raise RecoveryValidationError("failure kind 必须是字符串。")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            message=_text(payload.get("message"), "message"),
            step_id=payload.get("step_id"),  # type: ignore[arg-type]
            # type: ignore[arg-type]
            operation_key=payload.get("operation_key"),
            attempt=payload.get("attempt", 1),  # type: ignore[arg-type]
            evidence_refs=_texts(
                payload.get("evidence_refs", ()),
                "evidence_refs",
            ),
            # type: ignore[arg-type]
            outcome_known=payload.get("outcome_known", True),
            external_side_effect=payload.get(
                "external_side_effect", False
            ),  # type: ignore[arg-type]
        )


def failure_event_from_exception(
    exc: BaseException,
    *,
    step_id: str | None = None,
    operation_key: str | None = None,
    attempt: int = 1,
    evidence_refs: Iterable[str] = (),
) -> FailureEvent:
    """Map common runtime exceptions to a safe recovery classification."""

    resolved_operation_key = operation_key
    resolved_refs = list(evidence_refs)
    if isinstance(exc, RecoveryFailure):
        kind = exc.recovery_kind
        resolved_operation_key = resolved_operation_key or exc.operation_key
        resolved_refs.extend(exc.evidence_refs)
        outcome_known = exc.default_outcome_known
        external_side_effect = exc.default_external_side_effect
    elif isinstance(exc, TimeoutError):
        kind = "tool_timeout"
        outcome_known = True
        external_side_effect = False
    elif isinstance(exc, ConnectionError):
        kind = "database_disconnect"
        outcome_known = True
        external_side_effect = False
    else:
        kind = "tool_failure"
        outcome_known = True
        external_side_effect = False

    message = f"{type(exc).__name__}: {exc}".strip()
    if not message or message.endswith(":"):
        message = type(exc).__name__
    return FailureEvent(
        kind=kind,
        message=message,
        step_id=step_id,
        operation_key=resolved_operation_key,
        attempt=attempt,
        evidence_refs=tuple(dict.fromkeys(resolved_refs)),
        outcome_known=outcome_known,
        external_side_effect=external_side_effect,
    )


@dataclass(frozen=True)
class RecoveryDecision:
    """A safe next action derived from one failure event."""

    failure_kind: FailureKind
    action: RecoveryAction
    reason: str
    attempt: int
    delay_seconds: float = 0.0
    operation_key: str | None = None
    evidence_refs: tuple[str, ...] = ()
    requires_manual_intervention: bool = False

    def __post_init__(self) -> None:
        if self.failure_kind not in _FAILURE_KINDS:
            raise RecoveryValidationError(
                f"decision failure_kind 不合法：{self.failure_kind}。"
            )
        if self.action not in _RECOVERY_ACTIONS:
            raise RecoveryValidationError(
                f"recovery action 不合法：{self.action}。")
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RecoveryValidationError("decision attempt 必须是正整数。")
        if (
            not isinstance(self.delay_seconds, (int, float))
            or isinstance(self.delay_seconds, bool)
            or self.delay_seconds < 0
        ):
            raise RecoveryValidationError("delay_seconds 不能小于 0。")
        object.__setattr__(
            self,
            "operation_key",
            _optional_text(self.operation_key, "operation_key"),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _texts(self.evidence_refs, "evidence_refs"),
        )
        if not isinstance(self.requires_manual_intervention, bool):
            raise RecoveryValidationError(
                "requires_manual_intervention 必须是布尔值。"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "failure_kind": self.failure_kind,
            "action": self.action,
            "reason": self.reason,
            "attempt": self.attempt,
            "delay_seconds": self.delay_seconds,
            "operation_key": self.operation_key,
            "evidence_refs": list(self.evidence_refs),
            "requires_manual_intervention": self.requires_manual_intervention,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RecoveryDecision":
        failure_kind = payload.get("failure_kind", "tool_failure")
        action = payload.get("action", "manual_review")
        if not isinstance(failure_kind, str) or not isinstance(action, str):
            raise RecoveryValidationError("recovery decision 枚举字段无效。")
        return cls(
            failure_kind=failure_kind,  # type: ignore[arg-type]
            action=action,  # type: ignore[arg-type]
            reason=_text(payload.get("reason"), "reason"),
            attempt=payload.get("attempt", 1),  # type: ignore[arg-type]
            # type: ignore[arg-type]
            delay_seconds=payload.get("delay_seconds", 0.0),
            # type: ignore[arg-type]
            operation_key=payload.get("operation_key"),
            evidence_refs=_texts(
                payload.get("evidence_refs", ()),
                "evidence_refs",
            ),
            requires_manual_intervention=payload.get(
                "requires_manual_intervention", False
            ),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class RecoveryPolicy:
    """Finite retry policy with explicit paths for non-retryable failures."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts <= 0
        ):
            raise RecoveryValidationError("max_attempts 必须是正整数。")
        for field_name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("max_delay_seconds", self.max_delay_seconds),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise RecoveryValidationError(f"{field_name} 不能小于 0。")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise RecoveryValidationError(
                "max_delay_seconds 不能小于 base_delay_seconds。"
            )

    def backoff_seconds(self, attempt: int) -> float:
        """Return capped exponential backoff for the next attempt."""

        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            raise RecoveryValidationError("attempt 必须是正整数。")
        return min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt - 1)),
        )

    def decide(self, event: FailureEvent) -> RecoveryDecision:
        """Map one failure to exactly one bounded recovery action."""

        if event.kind == "unknown_external_result" or not event.outcome_known:
            if event.operation_key:
                return RecoveryDecision(
                    failure_kind=event.kind,
                    action="reconcile",
                    reason="外部副作用结果未知，先按 operation_key 核对，禁止盲目重放。",
                    attempt=event.attempt,
                    operation_key=event.operation_key,
                    evidence_refs=event.evidence_refs,
                    requires_manual_intervention=False,
                )
            return RecoveryDecision(
                failure_kind=event.kind,
                action="manual_review",
                reason="外部副作用结果未知且缺少 operation_key，必须人工核对。",
                attempt=event.attempt,
                evidence_refs=event.evidence_refs,
                requires_manual_intervention=True,
            )

        if event.kind == "worker_restart":
            return RecoveryDecision(
                failure_kind=event.kind,
                action="resume_checkpoint",
                reason="worker 已重启，先恢复 checkpoint 并校验版本一致性。",
                attempt=event.attempt,
                operation_key=event.operation_key,
                evidence_refs=event.evidence_refs,
            )

        if event.kind == "plan_invalidated":
            return RecoveryDecision(
                failure_kind=event.kind,
                action="replan",
                reason="新证据使当前计划假设失效，禁止继续执行旧计划。",
                attempt=event.attempt,
                operation_key=event.operation_key,
                evidence_refs=event.evidence_refs,
            )

        if event.kind == "verification_failure":
            return RecoveryDecision(
                failure_kind=event.kind,
                action="replan",
                reason="验证未通过，保留失败证据并进入修复或重规划。",
                attempt=event.attempt,
                operation_key=event.operation_key,
                evidence_refs=event.evidence_refs,
            )

        if event.kind in ("tool_timeout", "database_disconnect"):
            if event.attempt < self.max_attempts:
                return RecoveryDecision(
                    failure_kind=event.kind,
                    action="retry",
                    reason=(
                        "瞬时工具或数据库故障，按有限指数退避后重试。"
                    ),
                    attempt=event.attempt,
                    delay_seconds=self.backoff_seconds(event.attempt),
                    operation_key=event.operation_key,
                    evidence_refs=event.evidence_refs,
                )
            return RecoveryDecision(
                failure_kind=event.kind,
                action="blocked",
                reason="已达到最大重试次数，进入 blocked，等待人工介入。",
                attempt=event.attempt,
                operation_key=event.operation_key,
                evidence_refs=event.evidence_refs,
                requires_manual_intervention=True,
            )

        return RecoveryDecision(
            failure_kind=event.kind,
            action="manual_review",
            reason="非安全可重试故障，等待人工判断后再继续。",
            attempt=event.attempt,
            operation_key=event.operation_key,
            evidence_refs=event.evidence_refs,
            requires_manual_intervention=True,
        )


@dataclass(frozen=True)
class RecoverySource:
    """Version tuple read from one recovery source."""

    source: RecoverySourceKind
    run_id: str
    goal_id: str
    goal_version: int
    plan_version: int | None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in _RECOVERY_SOURCE_KINDS:
            raise RecoveryValidationError(
                f"recovery source 不合法：{self.source}。")
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if (
            not isinstance(self.goal_version, int)
            or isinstance(self.goal_version, bool)
            or self.goal_version <= 0
        ):
            raise RecoveryValidationError("goal_version 必须是正整数。")
        if self.plan_version is not None and (
            not isinstance(self.plan_version, int)
            or isinstance(self.plan_version, bool)
            or self.plan_version <= 0
        ):
            raise RecoveryValidationError("plan_version 必须是正整数或 null。")
        object.__setattr__(
            self,
            "evidence_refs",
            _texts(self.evidence_refs, "evidence_refs"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "goal_version": self.goal_version,
            "plan_version": self.plan_version,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RecoverySource":
        source = payload.get("source")
        if not isinstance(source, str):
            raise RecoveryValidationError("recovery source 必须是字符串。")
        return cls(
            source=source,  # type: ignore[arg-type]
            run_id=_text(payload.get("run_id"), "run_id"),
            goal_id=_text(payload.get("goal_id"), "goal_id"),
            goal_version=payload.get("goal_version"),  # type: ignore[arg-type]
            plan_version=payload.get("plan_version"),  # type: ignore[arg-type]
            evidence_refs=_texts(
                payload.get("evidence_refs", ()),
                "evidence_refs",
            ),
        )


def assert_recovery_consistency(sources: Iterable[RecoverySource]) -> None:
    """Reject recovery when checkpoint, run, and evidence versions diverge."""

    normalized = tuple(sources)
    by_name = {source.source: source for source in normalized}
    if len(by_name) != len(normalized):
        raise RecoveryConsistencyError("恢复来源不能重复。")
    missing = _RECOVERY_SOURCE_KINDS - set(by_name)
    if missing:
        raise RecoveryConsistencyError(
            "恢复缺少来源：" + ", ".join(sorted(missing)) + "。"
        )

    checkpoint = by_name["checkpoint"]
    mismatches: list[str] = []
    for source in normalized:
        for field_name in ("run_id", "goal_id", "goal_version", "plan_version"):
            expected = getattr(checkpoint, field_name)
            actual = getattr(source, field_name)
            if expected != actual:
                mismatches.append(
                    f"{source.source}.{field_name}={actual!r}"
                    f" != checkpoint.{field_name}={expected!r}"
                )
    if mismatches:
        raise RecoveryConsistencyError(
            "checkpoint、run、evidence 版本不一致："
            + "; ".join(mismatches)
        )


__all__ = [
    "DatabaseDisconnectedError",
    "FailureEvent",
    "FailureKind",
    "PlanInvalidatedError",
    "RecoveryAction",
    "RecoveryConsistencyError",
    "RecoveryFailure",
    "RecoveryDecision",
    "RecoveryPolicy",
    "RecoverySource",
    "RecoverySourceKind",
    "RecoveryValidationError",
    "ToolTimeoutError",
    "UnknownExternalResultError",
    "WorkerRestartError",
    "assert_recovery_consistency",
    "failure_event_from_exception",
]
