"""Long-horizon evaluation trace contracts for W17 Session 6.

The recorder is deliberately runtime-agnostic: a real executor can append
events as they happen, while the report computes the same metrics for every
run.  This makes recovery and completion evidence reviewable instead of
depending on a final model-generated paragraph.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

EvalEventKind = Literal[
    "tool_call",
    "tool_result",
    "failure",
    "compact",
    "checkpoint_save",
    "checkpoint_restore",
    "replan",
    "goal_drift",
    "completion",
]
EvalFinalStatus = Literal["succeeded", "failed", "blocked", "needs_review"]

_EVENT_KINDS = frozenset(
    {
        "tool_call",
        "tool_result",
        "failure",
        "compact",
        "checkpoint_save",
        "checkpoint_restore",
        "replan",
        "goal_drift",
        "completion",
    }
)


class LongHorizonEvalValidationError(ValueError):
    """Raised when an eval trace cannot prove the required experiment shape."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LongHorizonEvalValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise LongHorizonEvalValidationError(f"{field_name} 必须是字符串数组。")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{field_name}[{index}]"))
    return tuple(result)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value.strip()))


@dataclass(frozen=True)
class EvalEvent:
    """One ordered observation in a long-horizon run."""

    sequence: int
    kind: EvalEventKind
    name: str
    summary: str = ""
    step_id: str | None = None
    operation_key: str | None = None
    token_count: int = 0
    cost: float = 0.0
    latency_seconds: float = 0.0
    evidence_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence <= 0
        ):
            raise LongHorizonEvalValidationError("event.sequence 必须是正整数。")
        if self.kind not in _EVENT_KINDS:
            raise LongHorizonEvalValidationError(f"event.kind 不合法：{self.kind}。")
        object.__setattr__(self, "name", _text(self.name, "event.name"))
        object.__setattr__(self, "summary", self.summary.strip())
        if self.step_id is not None:
            object.__setattr__(self, "step_id", _text(self.step_id, "step_id"))
        if self.operation_key is not None:
            object.__setattr__(
                self,
                "operation_key",
                _text(self.operation_key, "operation_key"),
            )
        for field_name, value in (
            ("token_count", self.token_count),
            ("cost", self.cost),
            ("latency_seconds", self.latency_seconds),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise LongHorizonEvalValidationError(
                    f"event.{field_name} 不能小于 0。"
                )
        object.__setattr__(self, "evidence_refs", _dedupe(self.evidence_refs))
        if not isinstance(self.metadata, Mapping):
            raise LongHorizonEvalValidationError("event.metadata 必须是对象。")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EvalEvent":
        kind = payload.get("kind")
        if not isinstance(kind, str):
            raise LongHorizonEvalValidationError("event.kind 必须是字符串。")
        return cls(
            sequence=payload.get("sequence", 0),  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            name=_text(payload.get("name"), "event.name"),
            summary=str(payload.get("summary", "")),
            step_id=payload.get("step_id"),  # type: ignore[arg-type]
            operation_key=payload.get("operation_key"),  # type: ignore[arg-type]
            token_count=payload.get("token_count", 0),  # type: ignore[arg-type]
            cost=payload.get("cost", 0.0),  # type: ignore[arg-type]
            latency_seconds=payload.get("latency_seconds", 0.0),  # type: ignore[arg-type]
            evidence_refs=_texts(payload.get("evidence_refs", ()), "evidence_refs"),
            metadata=payload.get("metadata", {}),  # type: ignore[arg-type]
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "name": self.name,
            "summary": self.summary,
            "step_id": self.step_id,
            "operation_key": self.operation_key,
            "token_count": self.token_count,
            "cost": self.cost,
            "latency_seconds": self.latency_seconds,
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LongHorizonEvalReport:
    """Metrics and evidence emitted by one long-horizon experiment."""

    goal_id: str
    run_id: str
    target_tool_calls: int
    events: tuple[EvalEvent, ...]
    final_status: EvalFinalStatus
    tool_call_count: int
    failed_tool_call_count: int
    repeated_work_count: int
    goal_drift_count: int
    replan_count: int
    compact_count: int
    checkpoint_save_count: int
    checkpoint_restore_count: int
    total_tokens: int
    total_cost: float
    total_latency_seconds: float
    final_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        if not 30 <= self.target_tool_calls <= 50:
            raise LongHorizonEvalValidationError(
                "target_tool_calls 必须在 30 到 50 之间。"
            )
        if self.final_status not in (
            "succeeded",
            "failed",
            "blocked",
            "needs_review",
        ):
            raise LongHorizonEvalValidationError("final_status 不合法。")
        if any(not isinstance(event, EvalEvent) for event in self.events):
            raise LongHorizonEvalValidationError("events 只能包含 EvalEvent。")
        for field_name in (
            "tool_call_count",
            "failed_tool_call_count",
            "repeated_work_count",
            "goal_drift_count",
            "replan_count",
            "compact_count",
            "checkpoint_save_count",
            "checkpoint_restore_count",
            "total_tokens",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise LongHorizonEvalValidationError(f"{field_name} 不能小于 0。")
        for field_name in ("total_cost", "total_latency_seconds"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise LongHorizonEvalValidationError(f"{field_name} 不能小于 0。")
        object.__setattr__(
            self,
            "final_evidence_refs",
            _dedupe(self.final_evidence_refs),
        )

    @property
    def tool_success_rate(self) -> float:
        if self.tool_call_count == 0:
            return 0.0
        return round(
            (self.tool_call_count - self.failed_tool_call_count)
            / self.tool_call_count,
            3,
        )

    @property
    def ready(self) -> bool:
        """Whether the trace meets the W17 Session 6 completion gate."""

        return not self.readiness_issues

    @property
    def readiness_issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        if not 30 <= self.tool_call_count <= 50:
            issues.append("tool_call_count 不在 30–50 范围内")
        if self.replan_count == 0:
            issues.append("缺少 re-plan 事件")
        if self.compact_count == 0:
            issues.append("缺少 compact 事件")
        if self.checkpoint_restore_count == 0:
            issues.append("缺少 checkpoint 恢复事件")
        if self.failed_tool_call_count == 0:
            issues.append("缺少工具失败注入")
        if self.final_status != "succeeded":
            issues.append("最终状态不是 succeeded")
        if not self.final_evidence_refs:
            issues.append("缺少最终 evidence")
        return tuple(issues)

    def assert_ready(self) -> "LongHorizonEvalReport":
        """Raise instead of silently accepting an incomplete experiment."""

        if not self.ready:
            raise LongHorizonEvalValidationError(
                "Long-horizon eval 未完成：" + "；".join(self.readiness_issues)
            )
        return self

    @classmethod
    def from_events(
        cls,
        *,
        goal_id: str,
        run_id: str,
        events: Iterable[EvalEvent],
        final_status: EvalFinalStatus,
        target_tool_calls: int = 30,
        final_evidence_refs: Iterable[str] = (),
    ) -> "LongHorizonEvalReport":
        ordered = tuple(events)
        expected_sequences = tuple(range(1, len(ordered) + 1))
        actual_sequences = tuple(event.sequence for event in ordered)
        if actual_sequences != expected_sequences:
            raise LongHorizonEvalValidationError(
                "eval events 的 sequence 必须从 1 连续递增。"
            )
        tool_calls = tuple(event for event in ordered if event.kind == "tool_call")
        seen_operations: set[str] = set()
        repeated = 0
        for event in tool_calls:
            key = event.operation_key or f"{event.name}:{event.step_id or ''}"
            if key in seen_operations:
                repeated += 1
            seen_operations.add(key)
        failed = sum(
            1
            for event in ordered
            if event.kind == "failure"
            and str(event.metadata.get("failure_kind", "tool_failure"))
            in {"tool_failure", "tool_timeout", "database_disconnect"}
        )
        failed += sum(
            1
            for event in ordered
            if event.kind == "tool_result"
            and event.metadata.get("status") == "failed"
        )
        refs = _dedupe(
            (
                *final_evidence_refs,
                *(ref for event in ordered if event.kind == "completion" for ref in event.evidence_refs),
            )
        )
        return cls(
            goal_id=goal_id,
            run_id=run_id,
            target_tool_calls=target_tool_calls,
            events=ordered,
            final_status=final_status,
            tool_call_count=len(tool_calls),
            failed_tool_call_count=failed,
            repeated_work_count=repeated,
            goal_drift_count=sum(event.kind == "goal_drift" for event in ordered),
            replan_count=sum(event.kind == "replan" for event in ordered),
            compact_count=sum(event.kind == "compact" for event in ordered),
            checkpoint_save_count=sum(
                event.kind == "checkpoint_save" for event in ordered
            ),
            checkpoint_restore_count=sum(
                event.kind == "checkpoint_restore" for event in ordered
            ),
            total_tokens=sum(event.token_count for event in ordered),
            total_cost=round(sum(event.cost for event in ordered), 8),
            total_latency_seconds=round(
                sum(event.latency_seconds for event in ordered),
                6,
            ),
            final_evidence_refs=refs,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "LongHorizonEvalReport":
        raw_events = payload.get("events", ())
        if isinstance(raw_events, (str, bytes)) or not isinstance(raw_events, Sequence):
            raise LongHorizonEvalValidationError("events 必须是对象数组。")
        events = tuple(
            EvalEvent.from_dict(item)
            for item in raw_events
            if isinstance(item, Mapping)
        )
        if len(events) != len(raw_events):
            raise LongHorizonEvalValidationError("events 中存在非法元素。")
        final_status = payload.get("final_status")
        if not isinstance(final_status, str):
            raise LongHorizonEvalValidationError("final_status 必须是字符串。")
        return cls.from_events(
            goal_id=_text(payload.get("goal_id"), "goal_id"),
            run_id=_text(payload.get("run_id"), "run_id"),
            events=events,
            final_status=final_status,  # type: ignore[arg-type]
            target_tool_calls=payload.get("target_tool_calls", 30),  # type: ignore[arg-type]
            final_evidence_refs=_texts(
                payload.get("final_evidence_refs", ()),
                "final_evidence_refs",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "run_id": self.run_id,
            "target_tool_calls": self.target_tool_calls,
            "events": [event.as_dict() for event in self.events],
            "final_status": self.final_status,
            "tool_call_count": self.tool_call_count,
            "failed_tool_call_count": self.failed_tool_call_count,
            "tool_success_rate": self.tool_success_rate,
            "repeated_work_count": self.repeated_work_count,
            "goal_drift_count": self.goal_drift_count,
            "replan_count": self.replan_count,
            "compact_count": self.compact_count,
            "checkpoint_save_count": self.checkpoint_save_count,
            "checkpoint_restore_count": self.checkpoint_restore_count,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "total_latency_seconds": self.total_latency_seconds,
            "final_evidence_refs": list(self.final_evidence_refs),
            "ready": self.ready,
            "readiness_issues": list(self.readiness_issues),
        }


@dataclass
class LongHorizonEvalRecorder:
    """Append-only recorder that can wrap a real executor or worker."""

    goal_id: str
    run_id: str
    target_tool_calls: int = 30
    _events: list[EvalEvent] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.goal_id = _text(self.goal_id, "goal_id")
        self.run_id = _text(self.run_id, "run_id")
        if not 30 <= self.target_tool_calls <= 50:
            raise LongHorizonEvalValidationError(
                "target_tool_calls 必须在 30 到 50 之间。"
            )

    @property
    def events(self) -> tuple[EvalEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        kind: EvalEventKind,
        name: str,
        *,
        summary: str = "",
        step_id: str | None = None,
        operation_key: str | None = None,
        token_count: int = 0,
        cost: float = 0.0,
        latency_seconds: float = 0.0,
        evidence_refs: Iterable[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> EvalEvent:
        event = EvalEvent(
            sequence=len(self._events) + 1,
            kind=kind,
            name=name,
            summary=summary,
            step_id=step_id,
            operation_key=operation_key,
            token_count=token_count,
            cost=cost,
            latency_seconds=latency_seconds,
            evidence_refs=tuple(evidence_refs),
            metadata=metadata or {},
        )
        self._events.append(event)
        return event

    def record_tool_call(
        self,
        name: str,
        *,
        step_id: str | None = None,
        operation_key: str | None = None,
        token_count: int = 0,
        cost: float = 0.0,
        latency_seconds: float = 0.0,
        evidence_refs: Iterable[str] = (),
    ) -> EvalEvent:
        return self.record(
            "tool_call",
            name,
            step_id=step_id,
            operation_key=operation_key,
            token_count=token_count,
            cost=cost,
            latency_seconds=latency_seconds,
            evidence_refs=evidence_refs,
        )

    def record_tool_result(
        self,
        name: str,
        *,
        status: Literal["succeeded", "failed"] = "succeeded",
        summary: str = "",
        token_count: int = 0,
        cost: float = 0.0,
        latency_seconds: float = 0.0,
        evidence_refs: Iterable[str] = (),
    ) -> EvalEvent:
        return self.record(
            "tool_result",
            name,
            summary=summary,
            token_count=token_count,
            cost=cost,
            latency_seconds=latency_seconds,
            evidence_refs=evidence_refs,
            metadata={"status": status},
        )

    def record_failure(
        self,
        failure_kind: str,
        *,
        summary: str = "",
        step_id: str | None = None,
        evidence_refs: Iterable[str] = (),
    ) -> EvalEvent:
        return self.record(
            "failure",
            failure_kind,
            summary=summary,
            step_id=step_id,
            evidence_refs=evidence_refs,
            metadata={"failure_kind": _text(failure_kind, "failure_kind")},
        )

    def record_compaction(
        self,
        *,
        token_before: int = 0,
        token_after: int = 0,
        evidence_refs: Iterable[str] = (),
    ) -> EvalEvent:
        return self.record(
            "compact",
            "context.compact",
            token_count=token_after,
            evidence_refs=evidence_refs,
            metadata={"token_before": token_before, "token_after": token_after},
        )

    def record_checkpoint_restore(
        self,
        *,
        checkpoint_id: str,
        evidence_refs: Iterable[str] = (),
    ) -> EvalEvent:
        return self.record(
            "checkpoint_restore",
            "checkpoint.restore",
            summary=f"恢复 checkpoint：{checkpoint_id}",
            evidence_refs=evidence_refs,
            metadata={"checkpoint_id": _text(checkpoint_id, "checkpoint_id")},
        )

    def record_replan(
        self,
        *,
        summary: str,
        evidence_refs: Iterable[str],
    ) -> EvalEvent:
        return self.record(
            "replan",
            "planning.replan",
            summary=summary,
            evidence_refs=evidence_refs,
        )

    def record_goal_drift(
        self,
        *,
        summary: str,
        evidence_refs: Iterable[str],
    ) -> EvalEvent:
        return self.record(
            "goal_drift",
            "goal.drift",
            summary=summary,
            evidence_refs=evidence_refs,
        )

    def record_completion(
        self,
        *,
        status: EvalFinalStatus,
        evidence_refs: Iterable[str],
    ) -> EvalEvent:
        return self.record(
            "completion",
            "completion.gate",
            summary=f"最终状态：{status}",
            evidence_refs=evidence_refs,
            metadata={"status": status},
        )

    def report(
        self,
        *,
        final_status: EvalFinalStatus = "succeeded",
        final_evidence_refs: Iterable[str] = (),
    ) -> LongHorizonEvalReport:
        return LongHorizonEvalReport.from_events(
            goal_id=self.goal_id,
            run_id=self.run_id,
            events=self._events,
            final_status=final_status,
            target_tool_calls=self.target_tool_calls,
            final_evidence_refs=final_evidence_refs,
        )


def build_reference_long_horizon_eval(
    *,
    goal_id: str = "reference-goal",
    run_id: str = "reference-run",
    tool_calls: int = 30,
) -> LongHorizonEvalReport:
    """Build a fixed 30–50-call trace for wiring and report-shape checks.

    This is a deterministic reference trace, not a claim of production
    success.  Real experiments should feed the same recorder from the actual
    Planning/worker boundary and then call ``assert_ready``.
    """

    recorder = LongHorizonEvalRecorder(
        goal_id=goal_id,
        run_id=run_id,
        target_tool_calls=tool_calls,
    )
    for index in range(tool_calls):
        if index == 8:
            recorder.record_goal_drift(
                summary="探索发现原计划遗漏了配置入口。",
                evidence_refs=("trace:goal-drift",),
            )
        if index in (9, 19):
            recorder.record_compaction(
                token_before=7000,
                token_after=3500,
                evidence_refs=(f"compact:{index + 1}",),
            )
        if index == 14:
            recorder.record_replan(
                summary="根据根因 evidence 更新计划。",
                evidence_refs=("trace:replan",),
            )
        if index == 21:
            recorder.record_failure(
                "tool_failure",
                summary="一次搜索工具失败，按 recovery policy 重试。",
                evidence_refs=("failure:tool:21",),
            )
        if index == 22:
            recorder.record_checkpoint_restore(
                checkpoint_id="checkpoint:22",
                evidence_refs=("checkpoint:22",),
            )
        operation_key = f"inspect:{index}"
        if index == 17:
            operation_key = "inspect:16"
        recorder.record_tool_call(
            "repository.inspect",
            step_id=f"step-{index // 5 + 1}",
            operation_key=operation_key,
            token_count=120 + index,
            cost=0.0004,
            latency_seconds=0.12,
            evidence_refs=(f"tool:{index}",),
        )
    recorder.record_completion(
        status="succeeded",
        evidence_refs=("completion:all-criteria-pass",),
    )
    return recorder.report(
        final_status="succeeded",
        final_evidence_refs=("completion:all-criteria-pass",),
    )


__all__ = [
    "EvalEvent",
    "EvalEventKind",
    "EvalFinalStatus",
    "LongHorizonEvalRecorder",
    "LongHorizonEvalReport",
    "LongHorizonEvalValidationError",
    "build_reference_long_horizon_eval",
]
