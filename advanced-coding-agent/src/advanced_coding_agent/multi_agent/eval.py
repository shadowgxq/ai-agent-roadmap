"""W18 Session 6: paired single-agent v2 / multi-agent v3 evaluation.

Reuse the ten frozen tasks and baseline from w18_session_01.json. This module
summarizes observations; it never starts models, tools, tests, or workspaces.
Missing measurements stay None. A declared estimate is NOT a measured run.

Latency is end-to-end monotonic wall-clock time, NOT the sum of Worker/event
latencies. Cost and context tokens include Manager, routing, Workers, retries,
aggregation and verification. Context tokens mean cumulative prompt/input tokens;
peak_context_tokens is the separate per-call context limit check.

The host owns isolated workspace snapshots, independent grading, tool metering
and the side-effect audit. Those attestations cannot be reconstructed from a
Worker's final prose or from repeated task IDs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .decision import DecisionSuite, load_decision_suite
from .execution import WorkerExecutionReport

if TYPE_CHECKING:
    from ..long_horizon.eval import LongHorizonEvalReport

EvalMode = Literal["single-agent", "multi-agent"]
_MODES: tuple[EvalMode, ...] = ("single-agent", "multi-agent")


class MultiAgentEvalError(ValueError):
    """Incomparable, duplicated or malformed observations."""


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MultiAgentEvalError(f"{name} 必须是非空字符串。")


def _number(value: float, name: str, *, integer: bool = False) -> None:
    kind = int if integer else (int, float)
    if (not isinstance(value, kind) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0):
        raise MultiAgentEvalError(f"{name} 必须是非负有限{'整数' if integer else '数值'}。")


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def baseline_fingerprint(suite: DecisionSuite) -> str:
    return _fingerprint(asdict(suite.baseline))


def case_fingerprint(suite: DecisionSuite, case_id: str) -> str:
    for case in suite.cases:
        if case.profile.case_id == case_id:
            return _fingerprint(asdict(case))
    raise MultiAgentEvalError(f"未知 case_id：{case_id}")


@dataclass(frozen=True)
class EvalObservation:
    case_id: str
    mode: EvalMode
    run_id: str
    baseline_fingerprint: str
    case_fingerprint: str
    workspace_snapshot: str
    runtime_version: str
    verifier_version: str
    status: Literal["succeeded", "failed", "blocked", "needs_review"]
    verified_success: bool
    wall_clock_seconds: float
    tool_calls: int
    evidence_refs: tuple[str, ...]
    trial: int = 1
    kind: Literal["measured", "estimate", "fixture"] = "measured"
    currency: str = "USD"
    total_cost: float | None = None
    context_tokens: int | None = None
    peak_context_tokens: int | None = None
    duplicate_side_effects: int | None = None
    coordination_seconds: float | None = None
    accounting_complete: bool = False
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("case_id", "run_id", "baseline_fingerprint", "case_fingerprint",
                     "workspace_snapshot", "runtime_version", "verifier_version", "currency"):
            _text(getattr(self, name), name)
        if self.mode not in _MODES or self.kind not in ("measured", "estimate", "fixture"):
            raise MultiAgentEvalError("mode/kind 无效。")
        if self.status not in ("succeeded", "failed", "blocked", "needs_review"):
            raise MultiAgentEvalError("status 无效。")
        if not isinstance(self.verified_success, bool) or not isinstance(self.accounting_complete, bool):
            raise MultiAgentEvalError("verified_success/accounting_complete 必须是布尔值。")
        _number(self.trial, "trial", integer=True)
        if self.trial == 0:
            raise MultiAgentEvalError("trial 从 1 开始。")
        _number(self.wall_clock_seconds, "wall_clock_seconds")
        _number(self.tool_calls, "tool_calls", integer=True)
        for name in ("total_cost", "coordination_seconds", "context_tokens",
                     "peak_context_tokens", "duplicate_side_effects"):
            value = getattr(self, name)
            if value is not None:
                _number(value, name, integer=name in (
                    "context_tokens", "peak_context_tokens", "duplicate_side_effects"))
        if self.coordination_seconds is not None and self.coordination_seconds > self.wall_clock_seconds:
            raise MultiAgentEvalError("协调耗时是独占 wall-clock 区间，不能超过总耗时。")
        if (self.context_tokens is not None and self.peak_context_tokens is not None
                and self.peak_context_tokens > self.context_tokens):
            raise MultiAgentEvalError("峰值 context 不能超过累计 input tokens。")
        if not isinstance(self.evidence_refs, (tuple, list)):
            raise MultiAgentEvalError("evidence_refs 必须是字符串数组。")
        refs = tuple(self.evidence_refs)
        for ref in refs:
            _text(ref, "evidence_ref")
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(refs)))
        if self.verified_success and (self.status != "succeeded" or not refs):
            raise MultiAgentEvalError("成功必须同时具备终态成功和独立验收 evidence。")
        if self.failure_reason is not None:
            _text(self.failure_reason, "failure_reason")
        if self.status != "succeeded" and not self.failure_reason:
            raise MultiAgentEvalError("非成功终态必须记录 failure_reason。")
        if self.accounting_complete and any(value is None for value in (
            self.total_cost, self.context_tokens, self.peak_context_tokens,
        )):
            raise MultiAgentEvalError("完整计量必须包含成本、累计及峰值 context。")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AdoptionPolicy:
    """Explicit engineering thresholds, not statistical-significance claims."""

    min_cases: int = 10
    min_success_rate: float = 0.8
    min_success_gain: float = 0.1
    min_latency_reduction: float = 0.15
    max_cost_ratio: float = 1.5
    max_tool_ratio: float = 1.5
    max_context_ratio: float = 1.5
    max_latency_ratio: float = 1.1

    def __post_init__(self) -> None:
        _number(self.min_cases, "min_cases", integer=True)
        if self.min_cases < 10:
            raise MultiAgentEvalError("W18 完整对照至少需要 10 个不同任务。")
        for name in ("min_success_rate", "min_success_gain", "min_latency_reduction"):
            value = getattr(self, name)
            _number(value, name)
            if value > 1:
                raise MultiAgentEvalError(f"{name} 必须位于 [0, 1]。")
        for name in ("max_cost_ratio", "max_tool_ratio", "max_context_ratio", "max_latency_ratio"):
            value = getattr(self, name)
            _number(value, name)
            if value == 0:
                raise MultiAgentEvalError(f"{name} 必须大于 0。")


@dataclass(frozen=True)
class MultiAgentComparison:
    status: Literal["ready", "needs_data"]
    case_count: int
    expected_pairs: int
    measured_pairs: int
    metrics: Mapping[str, Mapping[str, object]]
    rows: tuple[Mapping[str, object], ...]
    recommendation: Literal["retain_multi_agent", "prefer_single_agent", "insufficient_data"]
    reasons: tuple[str, ...]
    issues: tuple[str, ...]
    policy: AdoptionPolicy

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mode"] = "multi-agent-eval"
        payload["definitions"] = {
            "success_rate": "独立验收成功数 / 配对运行数；越预算或重复副作用不计成功",
            "failure_rate": "1 - success_rate；包含 failed/blocked/review 和未通过验收",
            "latency": "端到端 wall-clock，不累加并行 Worker 耗时",
            "cost": "同币种全部角色、模型、工具与重试的总成本",
            "context_tokens": "所有模型调用的累计 input/prompt tokens，非峰值窗口",
            "coordination_seconds": "单独埋点的 Manager/路由/聚合独占 wall-clock；未知为 null",
        }
        return payload


def _budget_issues(suite: DecisionSuite, item: EvalObservation) -> list[str]:
    baseline = suite.baseline
    issues = []
    if item.tool_calls > baseline.max_tool_calls:
        issues.append("工具调用超预算")
    if item.wall_clock_seconds > baseline.timeout_seconds:
        issues.append("端到端超时")
    if item.peak_context_tokens is not None and item.peak_context_tokens > baseline.max_context_tokens:
        issues.append("峰值 context 超预算")
    return issues


def _success(suite: DecisionSuite, item: EvalObservation) -> bool:
    return (item.status == "succeeded" and item.verified_success
            and item.duplicate_side_effects in (None, 0) and not _budget_issues(suite, item))


def _metrics(suite: DecisionSuite, items: tuple[EvalObservation, ...]) -> dict[str, object]:
    count = len(items)
    success = sum(_success(suite, item) for item in items)
    def mean(name: str) -> float | None:
        values = [getattr(item, name) for item in items]
        return sum(values) / count if count and all(value is not None for value in values) else None
    return {
        "runs": count, "success_rate": success / count if count else None,
        "failure_rate": 1 - success / count if count else None,
        "mean_wall_clock_seconds": mean("wall_clock_seconds"),
        "mean_cost": mean("total_cost"), "mean_tool_calls": mean("tool_calls"),
        "mean_context_tokens": mean("context_tokens"),
        "mean_coordination_seconds": mean("coordination_seconds"),
        "total_duplicate_side_effects": (
            sum(item.duplicate_side_effects for item in items)
            if count and all(item.duplicate_side_effects is not None for item in items) else None
        ),
        "budget_violation_runs": sum(bool(_budget_issues(suite, item)) for item in items),
    }


def compare_multi_agent(
    suite: DecisionSuite, observations: Iterable[EvalObservation] = (), *,
    repetitions: int = 1, policy: AdoptionPolicy | None = None,
) -> MultiAgentComparison:
    """Compare only matched trials; never quietly discard failed measurements."""
    policy = policy or AdoptionPolicy()
    _number(repetitions, "repetitions", integer=True)
    if repetitions == 0:
        raise MultiAgentEvalError("repetitions 必须大于 0。")
    cases = {case.profile.case_id: case for case in suite.cases}
    baseline_hash = baseline_fingerprint(suite)
    records: dict[tuple[str, int, EvalMode], EvalObservation] = {}
    run_ids: dict[str, tuple[str, int, EvalMode]] = {}
    issues: list[str] = []
    for item in observations:
        if not isinstance(item, EvalObservation):
            raise MultiAgentEvalError("observations 只能包含 EvalObservation。")
        if item.case_id not in cases or item.trial > repetitions:
            raise MultiAgentEvalError("观测包含不在冻结任务集/重复次数中的运行。")
        if (item.baseline_fingerprint != baseline_hash
                or item.case_fingerprint != case_fingerprint(suite, item.case_id)):
            raise MultiAgentEvalError(f"{item.case_id} 的任务或模型/预算基线指纹不匹配。")
        key = (item.case_id, item.trial, item.mode)
        if key in records:
            if records[key] == item:
                continue
            raise MultiAgentEvalError(f"{key} 存在不同运行；不能挑选更好的结果覆盖。")
        if item.run_id in run_ids and run_ids[item.run_id] != key:
            raise MultiAgentEvalError("run_id 被不同 case/mode/trial 复用。")
        records[key] = item
        run_ids[item.run_id] = key

    rows: list[dict[str, object]] = []
    paired: dict[EvalMode, list[EvalObservation]] = {mode: [] for mode in _MODES}
    for case_id in cases:
        for trial in range(1, repetitions + 1):
            pair = [records.get((case_id, trial, mode)) for mode in _MODES]
            row: dict[str, object] = {
                "case_id": case_id, "trial": trial,
                "objective": cases[case_id].profile.objective,
                "single-agent": pair[0].as_dict() if pair[0] else None,
                "multi-agent": pair[1].as_dict() if pair[1] else None,
                "delta_multi_minus_single": None,
            }
            rows.append(row)
            label = f"{case_id}/trial-{trial}"
            if any(item is None for item in pair):
                issues.append(f"{label} 缺少配对运行。")
                continue
            single, multi = pair
            if any(item.kind != "measured" for item in pair):
                issues.append(f"{label} 含估算或 fixture，不视为实测。")
                continue
            for name in ("workspace_snapshot", "verifier_version", "currency"):
                if getattr(single, name) != getattr(multi, name):
                    raise MultiAgentEvalError(f"{label} 的 {name} 不同，比较无效。")
            if single.runtime_version != suite.baseline.runtime_version:
                raise MultiAgentEvalError(f"{label} 未使用冻结的 single-agent runtime。")
            for item in pair:
                paired[item.mode].append(item)
                if not item.accounting_complete:
                    issues.append(f"{label}/{item.mode} 计量不完整。")
                if item.duplicate_side_effects is None:
                    issues.append(f"{label}/{item.mode} 缺少重复副作用审计。")
            row["delta_multi_minus_single"] = {
                name: (getattr(multi, name) - getattr(single, name)
                       if getattr(multi, name) is not None and getattr(single, name) is not None else None)
                for name in ("wall_clock_seconds", "total_cost", "tool_calls", "context_tokens")
            }
    # A single report cannot average different currencies, rubric versions or
    # mixed implementations merely because individual pairs happened to match.
    if len({item.currency for values in paired.values() for item in values}) > 1:
        raise MultiAgentEvalError("一次报告只能使用一种币种。")
    if len({item.verifier_version for values in paired.values() for item in values}) > 1:
        raise MultiAgentEvalError("一次报告只能使用同一验收 rubric。")
    for mode in _MODES:
        if len({item.runtime_version for item in paired[mode]}) > 1:
            raise MultiAgentEvalError(f"{mode} 混入不同 runtime 版本。")
    metrics = {mode: _metrics(suite, tuple(paired[mode])) for mode in _MODES}
    if len(cases) < policy.min_cases:
        issues.append(f"仅 {len(cases)} 个不同任务，至少需要 {policy.min_cases} 个。")
    if issues:
        return MultiAgentComparison(
            "needs_data", len(cases), len(cases) * repetitions, len(paired["single-agent"]),
            metrics, tuple(rows), "insufficient_data",
            ("不完整观测不能证明拆分值得成本；保留单 Agent 作为默认。",),
            tuple(issues), policy,
        )
    single_metrics, multi_metrics = metrics["single-agent"], metrics["multi-agent"]
    reasons: list[str] = []
    # Multiplication avoids division by zero for a measured zero-cost baseline.
    for metric, limit in (
        ("mean_cost", policy.max_cost_ratio), ("mean_tool_calls", policy.max_tool_ratio),
        ("mean_context_tokens", policy.max_context_ratio),
        ("mean_wall_clock_seconds", policy.max_latency_ratio),
    ):
        if multi_metrics[metric] > single_metrics[metric] * limit:
            reasons.append(f"{metric} 超过配置的 {limit} 倍成本/资源上限。")
    if multi_metrics["total_duplicate_side_effects"]:
        reasons.append("multi-agent 存在重复副作用，不能采用。")
    if multi_metrics["budget_violation_runs"]:
        reasons.append("multi-agent 存在预算越界，不能采用。")
    quality_gain = multi_metrics["success_rate"] - single_metrics["success_rate"]
    latency_gain = (single_metrics["mean_wall_clock_seconds"] > 0 and
                    multi_metrics["mean_wall_clock_seconds"] <=
                    single_metrics["mean_wall_clock_seconds"] * (1 - policy.min_latency_reduction))
    if multi_metrics["success_rate"] < policy.min_success_rate or quality_gain < 0:
        reasons.append("成功率不达标或相较单 Agent 退步。")
    if not (quality_gain >= policy.min_success_gain or (quality_gain >= 0 and latency_gain)):
        reasons.append("质量提升或同质量下的延迟收益不足以支持拆分。")
    recommendation = "prefer_single_agent" if reasons else "retain_multi_agent"
    if not reasons:
        reasons.append("配对实测满足质量/延迟收益、资源上限和无重复副作用门槛。")
    reasons.append("这是配置阈值下的工程判断；不代表统计显著，建议后续增加重复试验。")
    return MultiAgentComparison(
        "ready", len(cases), len(cases) * repetitions, len(paired["single-agent"]),
        metrics, tuple(rows), recommendation, tuple(reasons), (), policy,
    )


def observation_from_worker_report(
    suite: DecisionSuite, case_id: str, report: WorkerExecutionReport, *,
    workspace_snapshot: str, verifier_version: str, verified_success: bool,
    evidence_refs: tuple[str, ...], runtime_version: str = "advanced-coding-agent-v3",
    trial: int = 1, total_cost: float | None = None, context_tokens: int | None = None,
    peak_context_tokens: int | None = None, duplicate_side_effects: int | None = None,
    coordination_seconds: float | None = None, accounting_complete: bool = False,
    currency: str = "USD",
) -> EvalObservation:
    safe_completion = (report.status == "completed" and not report.workspace_quarantined
                       and not report.outstanding_attempt_ids)
    return EvalObservation(
        case_id, "multi-agent", report.run_id, baseline_fingerprint(suite),
        case_fingerprint(suite, case_id), workspace_snapshot, runtime_version, verifier_version,
        "succeeded" if safe_completion else "blocked", verified_success and safe_completion,
        report.wall_clock_seconds, report.total_tool_calls, evidence_refs, trial=trial,
        total_cost=total_cost, context_tokens=context_tokens, peak_context_tokens=peak_context_tokens,
        duplicate_side_effects=duplicate_side_effects, coordination_seconds=coordination_seconds,
        accounting_complete=accounting_complete, currency=currency,
        failure_reason=None if safe_completion else "Worker 执行未完成、待核对或仍有未停止的 attempt。",
    )


def observation_from_long_horizon(
    suite: DecisionSuite, case_id: str, report: LongHorizonEvalReport, *,
    wall_clock_seconds: float, workspace_snapshot: str, verifier_version: str,
    verified_success: bool, evidence_refs: tuple[str, ...], trial: int = 1,
    total_cost: float | None = None, context_tokens: int | None = None,
    peak_context_tokens: int | None = None, duplicate_side_effects: int | None = None,
    accounting_complete: bool = False, currency: str = "USD",
) -> EvalObservation:
    """Do not mistake W17 event-latency sums or repeated reads for wall time/writes.

    Supply independently measured wall-clock and billing/input-token totals.
    Legacy report.total_tokens mixes token categories, so it is not copied.
    """
    return EvalObservation(
        case_id, "single-agent", report.run_id, baseline_fingerprint(suite),
        case_fingerprint(suite, case_id), workspace_snapshot, suite.baseline.runtime_version,
        verifier_version, report.final_status, verified_success,
        wall_clock_seconds, report.tool_call_count, evidence_refs, trial=trial,
        total_cost=total_cost, context_tokens=context_tokens, peak_context_tokens=peak_context_tokens,
        duplicate_side_effects=duplicate_side_effects, accounting_complete=accounting_complete,
        currency=currency, failure_reason=None if report.final_status == "succeeded"
        else f"W17 final_status={report.final_status}",
    )


def load_eval_observations(path: Path) -> tuple[EvalObservation, ...]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise MultiAgentEvalError("观测文件必须是 EvalObservation JSON 数组。")
        if any(not isinstance(item, dict) for item in payload):
            raise MultiAgentEvalError("每个观测必须是对象。")
        return tuple(EvalObservation(**item) for item in payload)
    except (OSError, ValueError, TypeError) as exc:
        raise MultiAgentEvalError(f"无法加载评估观测：{exc}") from exc


def load_eval_suite(path: Path) -> DecisionSuite:
    """Use the Session 1 frozen cases unchanged, including constraints and baseline."""
    return load_decision_suite(Path(path))


__all__ = [
    "AdoptionPolicy", "EvalMode", "EvalObservation", "MultiAgentComparison", "MultiAgentEvalError",
    "baseline_fingerprint", "case_fingerprint", "compare_multi_agent", "load_eval_observations",
    "load_eval_suite", "observation_from_long_horizon", "observation_from_worker_report",
]
