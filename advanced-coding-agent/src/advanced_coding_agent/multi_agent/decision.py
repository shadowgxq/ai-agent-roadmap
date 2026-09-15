"""W18 Session 1: decide whether a task deserves Multi-Agent splitting.

This module only freezes the comparison baseline and explains the split.  It
does not execute, route, or run workers; those capabilities belong to later
sessions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DecisionMode = Literal["single-agent", "multi-agent"]
SplitReason = Literal[
    "parallelization",
    "context_isolation",
    "specialization",
    "permission_isolation",
    "independent_verification",
]
WorkerRole = Literal["manager", "researcher", "coder", "tester"]
RiskLevel = Literal["low", "medium", "high"]

_REASON_ORDER: tuple[SplitReason, ...] = (
    "parallelization",
    "context_isolation",
    "specialization",
    "permission_isolation",
    "independent_verification",
)


class SplitDecisionValidationError(ValueError):
    """Raised when a baseline or decision case is malformed."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SplitDecisionValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SplitDecisionValidationError(f"{field_name} 必须是字符串数组。")
    values = tuple(_text(item, field_name) for item in value)
    if len(values) != len(set(values)):
        raise SplitDecisionValidationError(f"{field_name} 不能重复。")
    return values


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SplitDecisionValidationError(f"{field_name} 必须是对象。")
    return value


def _items(value: object, field_name: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SplitDecisionValidationError(f"{field_name} 必须是对象数组。")
    return tuple(
        _mapping(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True)
class BaselineSpec:
    """Conditions that single-agent and Multi-Agent runs must share."""

    baseline_id: str
    runtime_version: str
    model: str
    temperature: float
    tool_allowlist: tuple[str, ...]
    max_tool_calls: int
    max_context_tokens: int
    timeout_seconds: float
    success_metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.max_tool_calls <= 0 or self.max_context_tokens <= 0:
            raise SplitDecisionValidationError("baseline budget 必须大于 0。")
        if self.timeout_seconds <= 0:
            raise SplitDecisionValidationError("baseline timeout 必须大于 0。")
        if not self.tool_allowlist or not self.success_metrics:
            raise SplitDecisionValidationError("baseline tools/metrics 不能为空。")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BaselineSpec:
        return cls(
            baseline_id=_text(payload.get("id"), "baseline.id"),
            runtime_version=_text(
                payload.get("runtime_version"), "baseline.runtime_version"
            ),
            model=_text(payload.get("model"), "baseline.model"),
            temperature=float(payload.get("temperature", 0)),
            tool_allowlist=_texts(
                payload.get("tool_allowlist", ()), "baseline.tool_allowlist"
            ),
            max_tool_calls=int(payload.get("max_tool_calls", 0)),
            max_context_tokens=int(payload.get("max_context_tokens", 0)),
            timeout_seconds=float(payload.get("timeout_seconds", 0)),
            success_metrics=_texts(
                payload.get("success_metrics", ()), "baseline.success_metrics"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ParallelTaskCandidate:
    """A read-only task declared independent for latency estimation."""

    task_id: str
    description: str
    estimated_seconds: float
    context_scope: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.estimated_seconds <= 0 or not self.context_scope:
            raise SplitDecisionValidationError(
                f"parallel task {self.task_id} 需要正数耗时和 context scope。"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ParallelTaskCandidate:
        return cls(
            task_id=_text(payload.get("id"), "parallel_task.id"),
            description=_text(
                payload.get("description"), "parallel_task.description"
            ),
            estimated_seconds=float(payload.get("estimated_seconds", 0)),
            context_scope=_texts(
                payload.get("context_scope", ()), "parallel_task.context_scope"
            ),
        )


@dataclass(frozen=True)
class SplitProfile:
    """Facts used to decide whether complexity is actually splittable."""

    case_id: str
    objective: str
    complexity: Literal["simple", "complex"]
    parallel_tasks: tuple[ParallelTaskCandidate, ...]
    serial_path: tuple[str, ...]
    serial_duration_seconds: float
    coordination_overhead_seconds: float
    context_domains: tuple[str, ...]
    specialist_tools: tuple[str, ...]
    requires_write: bool
    requires_verification: bool
    risk_level: RiskLevel
    shared_write_targets: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.complexity not in ("simple", "complex"):
            raise SplitDecisionValidationError(
                "complexity 必须是 simple 或 complex。")
        if self.risk_level not in ("low", "medium", "high"):
            raise SplitDecisionValidationError("risk_level 不合法。")
        if not self.serial_path:
            raise SplitDecisionValidationError("serial_path 不能为空。")
        if self.serial_duration_seconds < 0 or self.coordination_overhead_seconds < 0:
            raise SplitDecisionValidationError("duration/overhead 不能小于 0。")
        task_ids = tuple(task.task_id for task in self.parallel_tasks)
        if len(task_ids) != len(set(task_ids)):
            raise SplitDecisionValidationError("parallel task id 不能重复。")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> SplitProfile:
        return cls(
            case_id=_text(payload.get("id"), "case.id"),
            objective=_text(payload.get("objective"), "case.objective"),
            complexity=payload.get("complexity"),  # type: ignore[arg-type]
            parallel_tasks=tuple(
                ParallelTaskCandidate.from_dict(item)
                for item in _items(payload.get("parallel_tasks", ()), "parallel_tasks")
            ),
            serial_path=_texts(payload.get("serial_path", ()), "serial_path"),
            serial_duration_seconds=float(
                payload.get("serial_duration_seconds", 0)
            ),
            coordination_overhead_seconds=float(
                payload.get("coordination_overhead_seconds", 0)
            ),
            context_domains=_texts(
                payload.get("context_domains", ()), "context_domains"
            ),
            specialist_tools=_texts(
                payload.get("specialist_tools", ()), "specialist_tools"
            ),
            # type: ignore[arg-type]
            requires_write=payload.get("requires_write", False),
            requires_verification=payload.get(  # type: ignore[arg-type]
                "requires_verification", False
            ),
            # type: ignore[arg-type]
            risk_level=payload.get("risk_level", "low"),
            shared_write_targets=_texts(
                payload.get("shared_write_targets", ()), "shared_write_targets"
            ),
            constraints=_texts(payload.get("constraints", ()), "constraints"),
        )


@dataclass(frozen=True)
class WorkerBoundary:
    role: WorkerRole
    responsibility: str
    tool_allowlist: tuple[str, ...]
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    bottleneck: str
    can_write: bool = False


@dataclass(frozen=True)
class CollaborationFlowEdge:
    """Data flow only; this is not a Session 3 route or Session 4 DAG edge."""

    source: str
    target: str
    payload: tuple[str, ...]


@dataclass(frozen=True)
class LatencyProjection:
    """An estimate that must later be replaced by wall-clock measurements."""

    sequential_seconds: float
    multi_agent_seconds: float

    @property
    def savings_seconds(self) -> float:
        return round(self.sequential_seconds - self.multi_agent_seconds, 3)

    @property
    def speedup_ratio(self) -> float:
        if self.multi_agent_seconds == 0:
            return 0.0
        return round(self.sequential_seconds / self.multi_agent_seconds, 3)

    @property
    def has_parallel_gain(self) -> bool:
        return self.savings_seconds > 0


@dataclass(frozen=True)
class SplitDecision:
    case_id: str
    baseline_id: str
    mode: DecisionMode
    reasons: tuple[SplitReason, ...]
    worker_boundaries: tuple[WorkerBoundary, ...]
    data_flow: tuple[CollaborationFlowEdge, ...]
    critical_path: tuple[str, ...]
    coordination_risks: tuple[str, ...]
    latency: LatencyProjection
    explanation: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["latency"]["savings_seconds"] = self.latency.savings_seconds
        payload["latency"]["speedup_ratio"] = self.latency.speedup_ratio
        payload["latency"]["kind"] = "estimate-not-measurement"
        return payload


_COMMON_RESULT = ("status", "summary", "evidence_refs", "recommendation")
_BOUNDARIES: Mapping[WorkerRole, WorkerBoundary] = {
    "manager": WorkerBoundary(
        role="manager",
        responsibility="拆分、分配、聚合并处理未解决冲突。",
        tool_allowlist=(),
        input_fields=("goal", "plan", "progress", "worker_summaries"),
        output_fields=("decision", "assignments", "unresolved_conflicts"),
        bottleneck="避免 Worker 自行扩大范围或互相覆盖责任。",
    ),
    "researcher": WorkerBoundary(
        role="researcher",
        responsibility="只读搜索代码、配置与验证证据。",
        tool_allowlist=("list_repository", "search_text", "read_file"),
        input_fields=("objective", "constraints", "context_scope"),
        output_fields=_COMMON_RESULT,
        bottleneck="隔离探索上下文，并承接安全的并行研究。",
    ),
    "coder": WorkerBoundary(
        role="coder",
        responsibility="依据已确认 evidence 完成最小代码修改。",
        tool_allowlist=("read_file", "edit_file"),
        input_fields=("change_task", "constraints", "evidence_refs"),
        output_fields=("status", "changed_files",
                       "evidence_refs", "recommendation"),
        bottleneck="把共享工作区写入收敛到单一角色。",
        can_write=True,
    ),
    "tester": WorkerBoundary(
        role="tester",
        responsibility="独立验证变更是否满足成功标准。",
        tool_allowlist=("read_file", "run_tests"),
        input_fields=("success_criteria", "changed_files", "diff"),
        output_fields=(
            "status",
            "verification_results",
            "evidence_refs",
            "recommendation",
        ),
        bottleneck="降低 Coder 自我确认造成的错误成功。",
    ),
}


class DeterministicSplitDecider:
    """Use visible rules before Session 3 introduces a structured router."""

    def decide(self, profile: SplitProfile, baseline: BaselineSpec) -> SplitDecision:
        unavailable = set(profile.specialist_tools) - \
            set(baseline.tool_allowlist)
        if unavailable:
            raise SplitDecisionValidationError(
                "specialist tools 不在 baseline 中：" +
                ", ".join(sorted(unavailable))
            )

        latency = self._project_latency(profile)
        reasons = self._reasons(profile, latency)
        mode = self._mode(profile, reasons, latency)
        boundaries = self._boundaries(profile, mode)
        return SplitDecision(
            case_id=profile.case_id,
            baseline_id=baseline.baseline_id,
            mode=mode,
            reasons=reasons,
            worker_boundaries=boundaries,
            data_flow=self._data_flow(boundaries, mode),
            critical_path=self._critical_path(profile),
            coordination_risks=self._risks(profile, mode),
            latency=latency,
            explanation=self._explanation(profile, mode, reasons, latency),
        )

    @staticmethod
    def _project_latency(profile: SplitProfile) -> LatencyProjection:
        durations = tuple(
            task.estimated_seconds for task in profile.parallel_tasks)
        return LatencyProjection(
            sequential_seconds=round(
                sum(durations) + profile.serial_duration_seconds, 3
            ),
            multi_agent_seconds=round(
                max(durations, default=0)
                + profile.serial_duration_seconds
                + profile.coordination_overhead_seconds,
                3,
            ),
        )

    @staticmethod
    def _reasons(
        profile: SplitProfile, latency: LatencyProjection
    ) -> tuple[SplitReason, ...]:
        reasons: set[SplitReason] = set()
        if len(profile.parallel_tasks) >= 2 and latency.has_parallel_gain:
            reasons.add("parallelization")
        if profile.complexity == "complex" and len(profile.context_domains) >= 2:
            reasons.add("context_isolation")
        if profile.complexity == "complex" and len(profile.specialist_tools) >= 2:
            reasons.add("specialization")
        if profile.requires_write and profile.parallel_tasks:
            reasons.add("permission_isolation")
        if profile.requires_write and profile.requires_verification:
            reasons.add("independent_verification")
        return tuple(reason for reason in _REASON_ORDER if reason in reasons)

    @staticmethod
    def _mode(
        profile: SplitProfile,
        reasons: tuple[SplitReason, ...],
        latency: LatencyProjection,
    ) -> DecisionMode:
        if profile.complexity == "simple":
            return "single-agent"
        has_parallel_gain = "parallelization" in reasons and latency.has_parallel_gain
        has_specialist_isolation = (
            "context_isolation" in reasons and "specialization" in reasons
        )
        needs_independent_high_risk_review = (
            profile.risk_level == "high" and "independent_verification" in reasons
        )
        if has_parallel_gain or has_specialist_isolation or needs_independent_high_risk_review:
            return "multi-agent"
        return "single-agent"

    @staticmethod
    def _boundaries(
        profile: SplitProfile, mode: DecisionMode
    ) -> tuple[WorkerBoundary, ...]:
        if mode == "single-agent":
            return ()
        roles: list[WorkerRole] = ["manager"]
        if profile.parallel_tasks or profile.context_domains or profile.specialist_tools:
            roles.append("researcher")
        if profile.requires_write:
            roles.append("coder")
        if profile.requires_verification:
            roles.append("tester")
        return tuple(_BOUNDARIES[role] for role in roles)

    @staticmethod
    def _data_flow(
        boundaries: tuple[WorkerBoundary, ...], mode: DecisionMode
    ) -> tuple[CollaborationFlowEdge, ...]:
        if mode == "single-agent":
            return (
                CollaborationFlowEdge(
                    "Goal/Plan/Progress",
                    "SingleAgent",
                    ("objective", "constraints", "success_criteria"),
                ),
                CollaborationFlowEdge(
                    "SingleAgent",
                    "CompletionGate",
                    ("status", "summary", "evidence_refs"),
                ),
            )

        edges = [
            CollaborationFlowEdge(
                "Goal/Plan/Progress",
                "Manager",
                ("objective", "constraints", "success_criteria"),
            )
        ]
        for boundary in boundaries:
            if boundary.role == "manager":
                continue
            worker = boundary.role.title()
            edges.extend(
                (
                    CollaborationFlowEdge(
                        "Manager",
                        worker,
                        ("assigned_task", "minimal_context", "budget"),
                    ),
                    CollaborationFlowEdge(
                        worker,
                        "Manager",
                        ("status", "summary", "evidence_refs", "recommendation"),
                    ),
                )
            )
        edges.append(
            CollaborationFlowEdge(
                "Manager",
                "CompletionGate",
                ("conclusion", "evidence_refs", "unresolved_conflicts"),
            )
        )
        return tuple(edges)

    @staticmethod
    def _critical_path(profile: SplitProfile) -> tuple[str, ...]:
        if not profile.parallel_tasks:
            return profile.serial_path
        slowest = max(profile.parallel_tasks,
                      key=lambda task: task.estimated_seconds)
        return (slowest.task_id, *profile.serial_path)

    @staticmethod
    def _risks(profile: SplitProfile, mode: DecisionMode) -> tuple[str, ...]:
        if mode == "single-agent":
            return ()
        risks = ["调度、上下文传递和结果聚合会增加固定开销。"]
        if profile.shared_write_targets:
            risks.append(
                "共享写入必须由 Coder 串行处理："
                + ", ".join(profile.shared_write_targets)
            )
        if len(profile.parallel_tasks) < 2:
            risks.append("拆分收益主要来自隔离或独立验证，而不是并行。")
        return tuple(risks)

    @staticmethod
    def _explanation(
        profile: SplitProfile,
        mode: DecisionMode,
        reasons: tuple[SplitReason, ...],
        latency: LatencyProjection,
    ) -> str:
        if mode == "multi-agent":
            return (
                f"拆分理由：{'、'.join(reasons)}；估算端到端耗时 "
                f"{latency.sequential_seconds}s → {latency.multi_agent_seconds}s。"
            )
        if profile.complexity == "simple":
            return "任务简单，Worker 初始化和聚合开销没有充分回报。"
        return "任务虽然复杂，但当前关键路径、风险或协调开销不足以支持拆分。"


@dataclass(frozen=True)
class DecisionCase:
    profile: SplitProfile
    expected_mode: DecisionMode
    expected_reasons: tuple[SplitReason, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DecisionCase:
        expected = _mapping(payload.get("expected"), "expected")
        mode = expected.get("mode")
        if mode not in ("single-agent", "multi-agent"):
            raise SplitDecisionValidationError("expected.mode 不合法。")
        reasons = _texts(expected.get("reasons", ()), "expected.reasons")
        if any(reason not in _REASON_ORDER for reason in reasons):
            raise SplitDecisionValidationError("expected.reasons 包含未知理由。")
        return cls(
            profile=SplitProfile.from_dict(payload),
            expected_mode=mode,  # type: ignore[arg-type]
            expected_reasons=reasons,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DecisionSuite:
    baseline: BaselineSpec
    cases: tuple[DecisionCase, ...]

    def __post_init__(self) -> None:
        if not self.cases:
            raise SplitDecisionValidationError("cases 不能为空。")
        case_ids = tuple(case.profile.case_id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise SplitDecisionValidationError("case id 不能重复。")


@dataclass(frozen=True)
class DecisionCaseResult:
    case: DecisionCase
    decision: SplitDecision

    @property
    def matches_expectation(self) -> bool:
        return (
            self.decision.mode == self.case.expected_mode
            and self.decision.reasons == self.case.expected_reasons
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "case": {
                "id": self.case.profile.case_id,
                "objective": self.case.profile.objective,
                "expected_mode": self.case.expected_mode,
                "expected_reasons": self.case.expected_reasons,
            },
            "decision": self.decision.as_dict(),
            "matches_expectation": self.matches_expectation,
        }


@dataclass(frozen=True)
class DecisionReport:
    baseline: BaselineSpec
    results: tuple[DecisionCaseResult, ...]

    @property
    def expectation_match_count(self) -> int:
        return sum(result.matches_expectation for result in self.results)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "multi-agent-split-decision",
            "baseline": self.baseline.as_dict(),
            "case_count": len(self.results),
            "single_agent_count": sum(
                result.decision.mode == "single-agent" for result in self.results
            ),
            "multi_agent_count": sum(
                result.decision.mode == "multi-agent" for result in self.results
            ),
            "expectation_match_count": self.expectation_match_count,
            "cases": [result.as_dict() for result in self.results],
        }


def evaluate_split_decisions(
    suite: DecisionSuite,
    decider: DeterministicSplitDecider | None = None,
) -> DecisionReport:
    active_decider = decider or DeterministicSplitDecider()
    return DecisionReport(
        baseline=suite.baseline,
        results=tuple(
            DecisionCaseResult(
                case=case,
                decision=active_decider.decide(case.profile, suite.baseline),
            )
            for case in suite.cases
        ),
    )


def load_decision_suite(path: Path) -> DecisionSuite:
    """Load the frozen baseline and cases without running the experiment."""

    try:
        payload = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "split-decision file",
        )
        return DecisionSuite(
            baseline=BaselineSpec.from_dict(
                _mapping(payload.get("baseline"), "baseline")
            ),
            cases=tuple(
                DecisionCase.from_dict(item)
                for item in _items(payload.get("cases"), "cases")
            ),
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise SplitDecisionValidationError(
            f"无法读取 split-decision case 文件 {path}: {exc}"
        ) from exc


__all__ = [
    "BaselineSpec",
    "CollaborationFlowEdge",
    "DecisionCase",
    "DecisionCaseResult",
    "DecisionMode",
    "DecisionReport",
    "DecisionSuite",
    "DeterministicSplitDecider",
    "LatencyProjection",
    "ParallelTaskCandidate",
    "RiskLevel",
    "SplitDecision",
    "SplitDecisionValidationError",
    "SplitProfile",
    "SplitReason",
    "WorkerBoundary",
    "WorkerRole",
    "evaluate_split_decisions",
    "load_decision_suite",
]
