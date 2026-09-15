"""W18 Session 3 routing contracts.

Routing selects the responsible Worker; it does not execute a Worker or
schedule dependencies. Explicit task kinds use deterministic rules first.
Unknown tasks can be handed to an injected structured router, and malformed or
low-confidence routing results are sent to Manager recovery.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from .decision import SplitDecisionValidationError, WorkerRole

RouteTaskKind = Literal["search", "edit", "verify", "unknown"]
RouteMethod = Literal["deterministic", "structured", "fallback"]
RouteStatus = Literal["routed", "needs_review", "blocked"]
RouteTarget = Literal["researcher", "coder", "tester", "manager_review"]
RouteFallback = Literal["manager_review", "ask_clarification", "blocked"]
RouteRecoveryAction = Literal["reassign", "manager_review", "blocked"]

_WORKER_TARGETS: tuple[WorkerRole, ...] = ("researcher", "coder", "tester")
_ROUTE_TARGETS = frozenset((*_WORKER_TARGETS, "manager_review"))
_ROUTE_KINDS = frozenset(("search", "edit", "verify", "unknown"))
_ROUTE_METHODS = frozenset(("deterministic", "structured", "fallback"))
_ROUTE_STATUSES = frozenset(("routed", "needs_review", "blocked"))
_ROUTE_FALLBACKS = frozenset(
    ("manager_review", "ask_clarification", "blocked")
)
_RECOVERY_ACTIONS = frozenset(("reassign", "manager_review", "blocked"))


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SplitDecisionValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SplitDecisionValidationError(f"{field_name} 必须是字符串数组。")
    values = tuple(_text(item, field_name) for item in value)
    if len(values) != len(set(values)):
        raise SplitDecisionValidationError(f"{field_name} 不能重复。")
    return values


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


@dataclass(frozen=True)
class RouteRequest:
    """Minimal task information available to a router."""

    task_id: str
    objective: str
    kind: RouteTaskKind = "unknown"
    constraints: tuple[str, ...] = ()
    input_context: tuple[str, ...] = ()
    requires_write: bool = False
    requires_verification: bool = False

    def __post_init__(self) -> None:
        _text(self.task_id, "route.task_id")
        _text(self.objective, "route.objective")
        if self.kind not in _ROUTE_KINDS:
            raise SplitDecisionValidationError("route.kind 不合法。")
        _texts(self.constraints, "route.constraints")
        _texts(self.input_context, "route.input_context")
        if not isinstance(self.requires_write, bool):
            raise SplitDecisionValidationError("route.requires_write 必须是布尔值。")
        if not isinstance(self.requires_verification, bool):
            raise SplitDecisionValidationError(
                "route.requires_verification 必须是布尔值。"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "kind": self.kind,
            "constraints": list(self.constraints),
            "input_context": list(self.input_context),
            "requires_write": self.requires_write,
            "requires_verification": self.requires_verification,
        }


@dataclass(frozen=True)
class StructuredRouteResult:
    """Validated output schema for an injected structured router."""

    worker_role: RouteTarget
    reason: str
    confidence: float
    fallback: RouteFallback = "manager_review"

    def __post_init__(self) -> None:
        if self.worker_role not in _ROUTE_TARGETS:
            raise SplitDecisionValidationError(
                "structured route.worker_role 不合法。"
            )
        _text(self.reason, "structured route.reason")
        if not 0 <= self.confidence <= 1:
            raise SplitDecisionValidationError(
                "structured route.confidence 必须在 0 到 1 之间。"
            )
        if self.fallback not in _ROUTE_FALLBACKS:
            raise SplitDecisionValidationError("structured route.fallback 不合法。")

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, object]
    ) -> StructuredRouteResult:
        if not isinstance(payload, Mapping):
            raise SplitDecisionValidationError(
                "structured route result 必须是对象。"
            )
        worker_role = payload.get("worker_role", payload.get("target"))
        try:
            confidence = float(payload.get("confidence", -1))
        except (TypeError, ValueError) as exc:
            raise SplitDecisionValidationError(
                "structured route.confidence 必须是数字。"
            ) from exc
        return cls(
            worker_role=worker_role,  # type: ignore[arg-type]
            reason=payload.get("reason"),  # type: ignore[arg-type]
            confidence=confidence,
            fallback=payload.get("fallback", "manager_review"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StructuredRouteResult:
        """Compatibility alias for callers using the repository's as_dict API."""

        return cls.from_mapping(payload)

    def as_dict(self) -> dict[str, object]:
        return {
            "worker_role": self.worker_role,
            "reason": self.reason,
            "confidence": self.confidence,
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class RouteDecision:
    """Observable routing result, including reason and safe fallback."""

    task_id: str
    worker_role: RouteTarget
    method: RouteMethod
    reason: str
    confidence: float
    fallback: RouteFallback = "manager_review"
    status: RouteStatus = "routed"
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.task_id, "route_decision.task_id")
        if self.worker_role not in _ROUTE_TARGETS:
            raise SplitDecisionValidationError(
                "route_decision.worker_role 不合法。"
            )
        if self.method not in _ROUTE_METHODS:
            raise SplitDecisionValidationError("route_decision.method 不合法。")
        if self.status not in _ROUTE_STATUSES:
            raise SplitDecisionValidationError("route_decision.status 不合法。")
        _text(self.reason, "route_decision.reason")
        if not 0 <= self.confidence <= 1:
            raise SplitDecisionValidationError(
                "route_decision.confidence 必须在 0 到 1 之间。"
            )
        if self.fallback not in _ROUTE_FALLBACKS:
            raise SplitDecisionValidationError("route_decision.fallback 不合法。")
        if self.worker_role == "manager_review" and self.status == "routed":
            raise SplitDecisionValidationError(
                "manager_review 路由不能标记为 routed。"
            )
        if self.worker_role != "manager_review" and self.status != "routed":
            raise SplitDecisionValidationError(
                "Worker 路由只有在 status=routed 时才可执行。"
            )
        if self.status != "routed" and not self.failure_reason:
            raise SplitDecisionValidationError(
                "非 routed 决策必须包含 failure_reason。"
            )
        _optional_text(self.failure_reason, "route_decision.failure_reason")

    @property
    def target(self) -> RouteTarget:
        """Alias used by callers that call the destination a target."""

        return self.worker_role

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "worker_role": self.worker_role,
            "target": self.worker_role,
            "method": self.method,
            "reason": self.reason,
            "confidence": self.confidence,
            "fallback": self.fallback,
            "status": self.status,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class RouteRecovery:
    """Manager's safe next step after routing cannot select a Worker."""

    task_id: str
    action: RouteRecoveryAction
    reason: str
    next_role: WorkerRole | None = None

    def __post_init__(self) -> None:
        _text(self.task_id, "route_recovery.task_id")
        if self.action not in _RECOVERY_ACTIONS:
            raise SplitDecisionValidationError("route_recovery.action 不合法。")
        _text(self.reason, "route_recovery.reason")
        if self.action == "reassign":
            if self.next_role not in _WORKER_TARGETS:
                raise SplitDecisionValidationError(
                    "reassign recovery 必须指定 Worker next_role。"
                )
        elif self.next_role is not None:
            raise SplitDecisionValidationError(
                "只有 reassign recovery 可以指定 next_role。"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "reason": self.reason,
            "next_role": self.next_role,
        }


@dataclass(frozen=True)
class RoutingEvent:
    sequence: int
    decision: RouteDecision

    def as_dict(self) -> dict[str, object]:
        return {"sequence": self.sequence, "decision": self.decision.as_dict()}


@dataclass
class RoutingTrace:
    """Append-only record of every route decision, including fallbacks."""

    _events: list[RoutingEvent] = field(default_factory=list, repr=False)

    @property
    def events(self) -> tuple[RoutingEvent, ...]:
        return tuple(self._events)

    def record(self, decision: RouteDecision) -> RoutingEvent:
        event = RoutingEvent(len(self._events) + 1, decision)
        self._events.append(event)
        return event

    def as_dict(self) -> dict[str, object]:
        return {"events": [event.as_dict() for event in self._events]}


class DeterministicRouter:
    """Route explicit task kinds without an additional model call."""

    _RULES: dict[RouteTaskKind, WorkerRole] = {
        "search": "researcher",
        "edit": "coder",
        "verify": "tester",
    }

    def route(self, request: RouteRequest) -> RouteDecision | None:
        target = self._RULES.get(request.kind)
        if target is None:
            return None

        conflict = self._conflict(request)
        if conflict is not None:
            return RouteDecision(
                task_id=request.task_id,
                worker_role="manager_review",
                method="deterministic",
                reason=conflict,
                confidence=1.0,
                fallback="ask_clarification",
                status="needs_review",
                failure_reason=conflict,
            )

        return RouteDecision(
            task_id=request.task_id,
            worker_role=target,
            method="deterministic",
            reason=f"task.kind={request.kind} 的固定规则匹配 {target}。",
            confidence=1.0,
        )

    @staticmethod
    def _conflict(request: RouteRequest) -> str | None:
        if request.kind == "search" and request.requires_write:
            return "搜索任务声明需要写权限，无法安全路由给只读 Researcher。"
        if request.kind == "verify" and request.requires_write:
            return "验证任务声明需要写权限，无法安全路由给只读 Tester。"
        return None


StructuredResolver = Callable[
    [RouteRequest], StructuredRouteResult | Mapping[str, object]
]


class StructuredRouter:
    """Validate structured routing output and downgrade unsafe results."""

    def __init__(
        self,
        resolver: StructuredResolver,
        *,
        min_confidence: float = 0.7,
    ) -> None:
        if not callable(resolver):
            raise SplitDecisionValidationError("structured resolver 必须可调用。")
        if not 0 <= min_confidence <= 1:
            raise SplitDecisionValidationError(
                "min_confidence 必须在 0 到 1 之间。"
            )
        self._resolver = resolver
        self.min_confidence = min_confidence

    def route(self, request: RouteRequest) -> RouteDecision:
        try:
            raw = self._resolver(request)
            result = (
                raw
                if isinstance(raw, StructuredRouteResult)
                else StructuredRouteResult.from_mapping(raw)
            )
        except Exception as exc:
            return self._failure(
                request,
                reason="Structured Router 输出无效，交由 Manager recovery。",
                failure_reason=str(exc),
                fallback="manager_review",
            )

        if result.worker_role == "manager_review":
            return self._failure(
                request,
                reason=result.reason,
                failure_reason="Structured Router 明确要求 Manager review。",
                fallback=result.fallback,
                confidence=result.confidence,
            )
        if result.confidence < self.min_confidence:
            return self._failure(
                request,
                reason="Structured Router 置信度低于安全阈值。",
                failure_reason=(
                    f"confidence={result.confidence:.3f} "
                    f"< min_confidence={self.min_confidence:.3f}。"
                ),
                fallback=result.fallback,
                confidence=result.confidence,
            )
        return RouteDecision(
            task_id=request.task_id,
            worker_role=result.worker_role,
            method="structured",
            reason=result.reason,
            confidence=result.confidence,
            fallback=result.fallback,
        )

    @staticmethod
    def _failure(
        request: RouteRequest,
        *,
        reason: str,
        failure_reason: str,
        fallback: RouteFallback,
        confidence: float = 0.0,
    ) -> RouteDecision:
        return RouteDecision(
            task_id=request.task_id,
            worker_role="manager_review",
            method="structured",
            reason=reason,
            confidence=confidence,
            fallback=fallback,
            status="blocked" if fallback == "blocked" else "needs_review",
            failure_reason=failure_reason,
        )


class TaskRouter:
    """Use deterministic rules first, then structured routing, then recovery."""

    def __init__(
        self,
        *,
        deterministic: DeterministicRouter | None = None,
        structured: StructuredRouter | None = None,
        trace: RoutingTrace | None = None,
    ) -> None:
        self.deterministic = deterministic or DeterministicRouter()
        self.structured = structured
        self.trace = trace

    def route(self, request: RouteRequest) -> RouteDecision:
        decision = self.deterministic.route(request)
        if decision is None and self.structured is not None:
            decision = self.structured.route(request)
        if decision is None:
            decision = RouteDecision(
                task_id=request.task_id,
                worker_role="manager_review",
                method="fallback",
                reason="任务没有匹配确定性规则，且未配置 Structured Router。",
                confidence=0.0,
                fallback="ask_clarification",
                status="needs_review",
                failure_reason=f"unknown task kind: {request.kind}",
            )
        if self.trace is not None:
            self.trace.record(decision)
        return decision


__all__ = [
    "DeterministicRouter",
    "RouteDecision",
    "RouteFallback",
    "RouteMethod",
    "RouteRecovery",
    "RouteRecoveryAction",
    "RouteRequest",
    "RouteStatus",
    "RouteTarget",
    "RouteTaskKind",
    "RoutingEvent",
    "RoutingTrace",
    "StructuredRouteResult",
    "StructuredRouter",
    "TaskRouter",
]
