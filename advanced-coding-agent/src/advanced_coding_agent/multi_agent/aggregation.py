"""W18 Session 5: evidence-backed conclusions, conflicts, and investigation.

A topic names an explicitly exclusive decision (for example primary_root_cause).
Claims are structured, not extracted by keyword matching from free text. Evidence
references must belong to the current Worker attempt. Verification is explicitly
bound to a claim: passing an unrelated test does NOT establish a root cause.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from ..verification.verifier import VerificationResult
from .collaboration import ManagerDecision, WorkerAssignment, WorkerResult
from .execution import TaskResultAggregator


class AggregationError(ValueError):
    """Malformed claim, evidence binding, or aggregation request."""


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AggregationError(f"{name} 必须是非空字符串。")
    return value.strip()


def _refs(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise AggregationError(f"{name} 必须是字符串数组。")
    refs = tuple(_text(value, name) for value in values)
    if len(refs) != len(set(refs)):
        raise AggregationError(f"{name} 不能重复。")
    return refs


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    task_id: str
    attempt_id: str
    topic: str
    conclusion: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("claim_id", "task_id", "attempt_id", "topic", "conclusion"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))


@dataclass(frozen=True)
class ClaimVerification:
    """Host binding between a concrete claim and an independent Tester check.

    pass supports THIS claim; fail refutes THIS claim; needs_review is unresolved.
    The host must not bind a generic suite pass to a causal claim without a
    check that actually discriminates that claim from the alternatives.
    """

    claim_id: str
    verifier_task_id: str
    verifier_attempt_id: str
    result: VerificationResult

    def __post_init__(self) -> None:
        for name in ("claim_id", "verifier_task_id", "verifier_attempt_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.result, VerificationResult):
            raise AggregationError("result 必须是 VerificationResult。")
        if not _refs(self.result.evidence_refs, "verification.evidence_refs"):
            raise AggregationError("验证结果缺少 evidence。")
        if self.result.status == "pass" and (
            self.result.failed_checks or any(not check.passed for check in self.result.checks)
        ):
            raise AggregationError("pass 与 failed_checks 不一致。")


@dataclass(frozen=True)
class TopicConclusion:
    topic: str
    conclusion: str
    evidence_refs: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class EvidenceConflict:
    topic: str
    alternatives: tuple[str, ...]
    claim_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class InvestigationRequest:
    topic: str
    objective: str
    evidence_refs: tuple[str, ...]
    role: Literal["researcher"] = "researcher"
    constraints: tuple[str, ...] = (
        "只读调查，不修改文件或数据库。",
        "为每个候选解释寻找支持及反证，不以投票代替证据。",
        "需要执行测试时交给独立 Tester，不能与 Coder 并发。",
    )


@dataclass(frozen=True)
class AggregationReport:
    status: Literal["accepted", "investigate", "needs_review"]
    conclusions: tuple[TopicConclusion, ...]
    evidence_refs: tuple[str, ...]
    unresolved_conflicts: tuple[EvidenceConflict, ...]
    next_steps: tuple[InvestigationRequest, ...]
    issues: tuple[str, ...]
    ignored_claim_ids: tuple[str, ...]
    rejected_claim_ids: tuple[str, ...]
    source_attempts: tuple[tuple[str, str], ...]
    investigation_round: int

    @property
    def can_write(self) -> bool:
        return (self.status == "accepted" and bool(self.conclusions)
                and not self.issues and not self.unresolved_conflicts)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["can_write"] = self.can_write
        return payload

    def write_decision(
        self, assignment: WorkerAssignment, dependencies: Mapping[str, WorkerResult],
    ) -> ManagerDecision:
        """Adapt this review to the executor's pre-write gate.

        A stale report cannot approve different dependency attempts. All source
        evidence must be explicitly in the Coder's dependency set, not hidden in
        a captured global context.
        """
        actual = {task_id: result.attempt_id for task_id, result in dependencies.items()}
        versions_match = bool(actual) and dict(self.source_attempts) == actual
        evidence = {ref for result in dependencies.values() for ref in result.evidence_refs}
        allowed = (assignment.role == "coder" and self.can_write and versions_match
                   and bool(self.evidence_refs) and set(self.evidence_refs) <= evidence)
        return ManagerDecision(
            assignment.assignment_id, "accept" if allowed else "pause",
            "证据聚合通过且依赖版本匹配。" if allowed
            else "结论冲突、证据不足或聚合版本过期，禁止启动 Coder。",
            accepted_evidence_refs=self.evidence_refs if allowed else (),
        )


class EvidenceAggregator:
    """Conservative arbitration: no majority vote and no confidence guessing."""

    def __init__(self, *, max_investigation_rounds: int = 1) -> None:
        if (not isinstance(max_investigation_rounds, int)
                or isinstance(max_investigation_rounds, bool) or max_investigation_rounds < 0):
            raise AggregationError("max_investigation_rounds 必须是非负整数。")
        self.max_investigation_rounds = max_investigation_rounds

    def aggregate(
        self, results: Iterable[WorkerResult], claims: Iterable[EvidenceClaim], *,
        required_topics: tuple[str, ...], verifications: Iterable[ClaimVerification] = (),
        investigation_round: int = 0, require_verification: bool = False,
    ) -> AggregationReport:
        topics = _refs(required_topics, "required_topics")
        if not topics:
            raise AggregationError("必须声明待决策的 required_topics。")
        if (not isinstance(investigation_round, int) or isinstance(investigation_round, bool)
                or investigation_round < 0):
            raise AggregationError("investigation_round 必须是非负整数。")
        if not isinstance(require_verification, bool):
            raise AggregationError("require_verification 必须是布尔值。")
        current = TaskResultAggregator.from_results(results).by_task_id
        claims = tuple(claims)
        if any(not isinstance(item, EvidenceClaim) for item in claims):
            raise AggregationError("claims 只能包含 EvidenceClaim。")
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise AggregationError("claim_id 必须唯一，重试必须产生新 claim_id。")
        issues: list[str] = []
        ignored: list[str] = []
        valid: dict[str, EvidenceClaim] = {}
        for claim in claims:
            worker = current.get(claim.task_id)
            if worker is not None and worker.attempt_id != claim.attempt_id:
                ignored.append(claim.claim_id)
                continue
            if claim.topic not in topics:
                issues.append(f"claim {claim.claim_id} 超出 required_topics。")
            elif worker is None or worker.status != "succeeded" or not worker.outcome_known:
                issues.append(f"claim {claim.claim_id} 缺少当前成功的 Worker 结果。")
            elif not claim.evidence_refs or not set(claim.evidence_refs) <= set(worker.evidence_refs):
                issues.append(f"claim {claim.claim_id} 缺少可追溯的 Worker evidence。")
            elif worker.role == "researcher" and worker.side_effect_status != "none":
                issues.append(f"Researcher {worker.task_id} 越过只读权限。")
            else:
                valid[claim.claim_id] = claim

        checks: dict[str, list[ClaimVerification]] = {key: [] for key in valid}
        for check in verifications:
            if not isinstance(check, ClaimVerification):
                raise AggregationError("verifications 只能包含 ClaimVerification。")
            if check.claim_id in ignored:
                continue
            claim = valid.get(check.claim_id)
            tester = current.get(check.verifier_task_id)
            if (tester is not None and tester.attempt_id != check.verifier_attempt_id):
                continue  # An obsolete Tester attempt cannot settle a current dispute.
            if (claim is None or tester is None or tester.role != "tester"
                    or tester.task_id == claim.task_id or not tester.outcome_known
                    or tester.status not in ("succeeded", "failed", "needs_review")
                    or (check.result.status == "pass" and tester.status != "succeeded")
                    or not set(check.result.evidence_refs) <= set(tester.evidence_refs)):
                issues.append(f"claim {check.claim_id} 的独立验证绑定无效。")
                continue
            if check not in checks[claim.claim_id]:
                checks[claim.claim_id].append(check)

        conclusions: list[TopicConclusion] = []
        conflicts: list[EvidenceConflict] = []
        rejected: list[str] = []
        used_refs: list[str] = []
        for topic in topics:
            group = tuple(claim for claim in valid.values() if claim.topic == topic)
            alternatives = tuple(sorted({claim.conclusion for claim in group}))
            evidence = tuple(dict.fromkeys(
                [ref for claim in group for ref in claim.evidence_refs]
                + [ref for claim in group for check in checks[claim.claim_id]
                   for ref in check.result.evidence_refs]
            ))
            used_refs.extend(evidence)
            states: dict[str, str] = {}
            for alternative in alternatives:
                claim_states: list[str] = []
                for claim in group:
                    if claim.conclusion != alternative:
                        continue
                    verdicts = {check.result.status for check in checks[claim.claim_id]}
                    state = ("refuted" if verdicts == {"fail"} else
                             "supported" if verdicts == {"pass"} else
                             "unverified" if not verdicts else "disputed")
                    claim_states.append(state)
                    if state == "refuted":
                        rejected.append(claim.claim_id)
                states[alternative] = (
                    "refuted" if all(state == "refuted" for state in claim_states)
                    else "disputed" if "disputed" in claim_states or "refuted" in claim_states
                    else "supported" if "supported" in claim_states else "unverified"
                )
            winner = None
            if len(alternatives) == 1:
                candidate = alternatives[0]
                if states[candidate] == "supported" or (
                    states[candidate] == "unverified" and not require_verification
                ):
                    winner = candidate
            elif len(alternatives) > 1:
                supported = [value for value, state in states.items() if state == "supported"]
                if len(supported) == 1 and all(
                    state == "refuted" for value, state in states.items() if value != supported[0]
                ):
                    winner = supported[0]
            if winner is not None:
                conclusions.append(TopicConclusion(
                    topic, winner, evidence,
                    "独立验证支持唯一结论并排除了其他解释。" if len(alternatives) > 1
                    else "结论有证据且没有未解决的反证。",
                ))
            else:
                conflicts.append(EvidenceConflict(
                    topic, alternatives, tuple(claim.claim_id for claim in group), evidence,
                    "缺少可接受的结论。" if not group
                    else "证据/验证尚不能排除竞争解释，保留分歧。",
                ))

        status: Literal["accepted", "investigate", "needs_review"]
        if issues:
            status = "needs_review"
        elif conflicts:
            status = ("investigate" if investigation_round < self.max_investigation_rounds
                      else "needs_review")
        else:
            status = "accepted"
        next_steps = tuple(InvestigationRequest(
            conflict.topic,
            f"调查 {conflict.topic}：比较 {', '.join(conflict.alternatives) or '缺失结论'}；"
            "补充可区分假设的只读证据，必要时请求独立验证。",
            conflict.evidence_refs,
        ) for conflict in conflicts) if status == "investigate" else ()
        return AggregationReport(
            status, tuple(conclusions), tuple(dict.fromkeys(used_refs)), tuple(conflicts),
            next_steps, tuple(issues), tuple(ignored), tuple(rejected),
            tuple(sorted((task_id, result.attempt_id) for task_id, result in current.items())),
            investigation_round,
        )


def build_cache_database_conflict() -> tuple[tuple[WorkerResult, ...], tuple[EvidenceClaim, ...]]:
    """Declared learning fixture, NOT evidence from a real incident or an executed test."""
    research = WorkerResult(
        "fixture:research", "fixture:research", "researcher", "succeeded",
        "缓存命中日志提示缓存失效可能是主因。", ("fixture:cache-log",),
    )
    tester = WorkerResult(
        "fixture:tester", "fixture:tester", "tester", "succeeded",
        "数据库调用日志提示连接池耗尽可能是主因。", ("fixture:db-log",),
    )
    claims = (
        EvidenceClaim("fixture:cache", research.task_id, research.attempt_id,
                      "primary_root_cause", "cache", research.evidence_refs),
        EvidenceClaim("fixture:database", tester.task_id, tester.attempt_id,
                      "primary_root_cause", "database", tester.evidence_refs),
    )
    return (research, tester), claims


__all__ = [
    "AggregationError", "AggregationReport", "ClaimVerification", "EvidenceAggregator",
    "EvidenceClaim", "EvidenceConflict", "InvestigationRequest", "TopicConclusion",
    "build_cache_database_conflict",
]
