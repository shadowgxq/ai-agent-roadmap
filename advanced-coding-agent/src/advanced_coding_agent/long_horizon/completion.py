"""Evidence-backed completion gates for W17 Session 5.

Step verification answers "did this step work?".  The completion gate answers
the stronger question "did the whole Goal satisfy every frozen criterion?".
Keeping the two contracts separate prevents a successful last step from being
mistaken for a successful run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from ..verification import (
    ContentRequirement,
    DeterministicVerifier,
    EvidenceBackedSemanticVerifier,
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from .goal import Goal, SuccessCriterion

CompletionStatus = Literal["succeeded", "failed", "needs_review"]
CompletionCriterionStatus = VerificationStatus


class CompletionValidationError(ValueError):
    """Raised when a completion result is not safe to persist."""


class SemanticCriterionVerifier(Protocol):
    """Protocol for an evidence-bounded semantic/LLM verifier."""

    def verify(
        self,
        criterion: SuccessCriterion,
        evidence_refs: tuple[str, ...],
    ) -> VerificationResult:
        """Return pass/fail/needs_review for one semantic criterion."""


SemanticCriterionEvaluator = Callable[
    [SuccessCriterion, tuple[str, ...]], VerificationResult
]


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompletionValidationError(f"{field_name} 必须是非空字符串。")
    return value.strip()


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CompletionValidationError(f"{field_name} 必须是字符串数组。")
    refs: list[str] = []
    for index, item in enumerate(value):
        refs.append(_text(item, f"{field_name}[{index}]"))
    return tuple(refs)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value.strip()))


@dataclass(frozen=True)
class CriterionEvaluation:
    """Persisted result for one Goal success criterion."""

    criterion_id: str
    status: CompletionCriterionStatus
    summary: str
    evidence_refs: tuple[str, ...]
    checks: tuple[VerificationCheck, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "criterion_id", _text(self.criterion_id, "criterion_id"))
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        if self.status not in ("pass", "fail", "needs_review"):
            raise CompletionValidationError("criterion status 不合法。")
        refs = _texts(self.evidence_refs, "evidence_refs")
        if not refs:
            raise CompletionValidationError("criterion 必须包含 evidence_refs。")
        if any(not isinstance(check, VerificationCheck) for check in self.checks):
            raise CompletionValidationError("checks 只能包含 VerificationCheck。")
        object.__setattr__(self, "evidence_refs", _dedupe(refs))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CriterionEvaluation":
        raw_checks = payload.get("checks", ())
        if isinstance(raw_checks, (str, bytes)) or not isinstance(raw_checks, Sequence):
            raise CompletionValidationError("checks 必须是对象数组。")
        checks: list[VerificationCheck] = []
        for index, raw_check in enumerate(raw_checks):
            if not isinstance(raw_check, Mapping):
                raise CompletionValidationError(f"checks[{index}] 必须是对象。")
            checks.append(
                VerificationCheck(
                    name=_text(raw_check.get("name"), f"checks[{index}].name"),
                    passed=raw_check.get("passed") is True,
                    evidence_ref=_text(
                        raw_check.get("evidence_ref"),
                        f"checks[{index}].evidence_ref",
                    ),
                    detail=_text(raw_check.get("detail"), f"checks[{index}].detail"),
                )
            )
        status = payload.get("status")
        if not isinstance(status, str):
            raise CompletionValidationError("criterion status 必须是字符串。")
        return cls(
            criterion_id=_text(payload.get("criterion_id"), "criterion_id"),
            status=status,  # type: ignore[arg-type]
            summary=_text(payload.get("summary"), "summary"),
            evidence_refs=_texts(payload.get("evidence_refs", ()), "evidence_refs"),
            checks=tuple(checks),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "checks": [check.as_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class CompletionResult:
    """Aggregate completion-gate result for one Goal version."""

    status: CompletionStatus
    summary: str
    criteria: tuple[CriterionEvaluation, ...]
    evidence_refs: tuple[str, ...]
    failed_criteria: tuple[str, ...] = ()
    review_criteria: tuple[str, ...] = ()
    requires_manual_intervention: bool = False

    def __post_init__(self) -> None:
        if self.status not in ("succeeded", "failed", "needs_review"):
            raise CompletionValidationError("completion status 不合法。")
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        if any(not isinstance(item, CriterionEvaluation) for item in self.criteria):
            raise CompletionValidationError("criteria 只能包含 CriterionEvaluation。")
        criterion_ids = [item.criterion_id for item in self.criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise CompletionValidationError("criteria 的 id 不能重复。")
        refs = _texts(self.evidence_refs, "evidence_refs")
        if not refs:
            raise CompletionValidationError("completion 必须包含 evidence_refs。")
        failed = _texts(self.failed_criteria, "failed_criteria")
        review = _texts(self.review_criteria, "review_criteria")
        if self.status == "succeeded" and (failed or review):
            raise CompletionValidationError("succeeded 不能包含失败或待复核 criterion。")
        if self.status == "needs_review" and not self.requires_manual_intervention:
            raise CompletionValidationError("needs_review 必须要求人工介入。")
        if not isinstance(self.requires_manual_intervention, bool):
            raise CompletionValidationError("requires_manual_intervention 必须是布尔值。")
        object.__setattr__(self, "evidence_refs", _dedupe(refs))
        object.__setattr__(self, "failed_criteria", _dedupe(failed))
        object.__setattr__(self, "review_criteria", _dedupe(review))

    @property
    def passed(self) -> bool:
        """Whether the Goal may enter its terminal succeeded state."""

        return self.status == "succeeded"

    @property
    def verification_status(self) -> Literal["pass", "fail", "needs_review"]:
        """Expose the verifier vocabulary used by W16 callers."""

        return {
            "succeeded": "pass",
            "failed": "fail",
            "needs_review": "needs_review",
        }[self.status]  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CompletionResult":
        raw_criteria = payload.get("criteria", ())
        if isinstance(raw_criteria, (str, bytes)) or not isinstance(
            raw_criteria,
            Sequence,
        ):
            raise CompletionValidationError("criteria 必须是对象数组。")
        criteria = tuple(
            CriterionEvaluation.from_dict(item)
            for item in raw_criteria
            if isinstance(item, Mapping)
        )
        if len(criteria) != len(raw_criteria):
            raise CompletionValidationError("criteria 中存在非法元素。")
        status = payload.get("status")
        if not isinstance(status, str):
            raise CompletionValidationError("completion status 必须是字符串。")
        return cls(
            status=status,  # type: ignore[arg-type]
            summary=_text(payload.get("summary"), "summary"),
            criteria=criteria,
            evidence_refs=_texts(payload.get("evidence_refs", ()), "evidence_refs"),
            failed_criteria=_texts(
                payload.get("failed_criteria", ()),
                "failed_criteria",
            ),
            review_criteria=_texts(
                payload.get("review_criteria", ()),
                "review_criteria",
            ),
            requires_manual_intervention=payload.get(
                "requires_manual_intervention",
                False,
            ),  # type: ignore[arg-type]
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "verification_status": self.verification_status,
            "summary": self.summary,
            "criteria": [criterion.as_dict() for criterion in self.criteria],
            "evidence_refs": list(self.evidence_refs),
            "failed_criteria": list(self.failed_criteria),
            "review_criteria": list(self.review_criteria),
            "requires_manual_intervention": self.requires_manual_intervention,
        }


# A report is the same durable object; the alias makes the intent clear to
# callers that consume a completed run rather than an individual check.
CompletionReport = CompletionResult


class CompletionGate:
    """Run every frozen criterion before a run can be marked succeeded."""

    def __init__(
        self,
        *,
        deterministic_verifier: DeterministicVerifier | None = None,
        semantic_verifier: (
            SemanticCriterionVerifier
            | SemanticCriterionEvaluator
            | object
            | None
        ) = None,
    ) -> None:
        self._deterministic_verifier = deterministic_verifier or DeterministicVerifier()
        self._semantic_verifier = semantic_verifier

    def evaluate(
        self,
        goal: Goal,
        workdir: Path,
        *,
        evidence_refs: Iterable[str] = (),
        changed_paths: Iterable[str] = (),
    ) -> CompletionResult:
        """Evaluate all criteria and return a checkpoint-safe aggregate."""

        if not isinstance(goal, Goal):
            raise CompletionValidationError("goal 必须是 Goal。")
        root = Path(workdir).resolve()
        base_refs = _dedupe(evidence_refs)
        changed = tuple(_text(path, "changed_paths") for path in changed_paths)
        evaluations = tuple(
            self._evaluate_criterion(
                criterion,
                root,
                evidence_refs=base_refs,
                changed_paths=changed,
            )
            for criterion in goal.success_criteria
        )
        failed = tuple(
            result.criterion_id
            for result in evaluations
            if result.status == "fail"
        )
        review = tuple(
            result.criterion_id
            for result in evaluations
            if result.status == "needs_review"
        )
        if failed:
            status: CompletionStatus = "failed"
            summary = f"完成度验证失败：{', '.join(failed)}。"
            manual = False
        elif review:
            status = "needs_review"
            summary = f"完成度验证待人工复核：{', '.join(review)}。"
            manual = True
        else:
            status = "succeeded"
            summary = f"完成度验证通过，共 {len(evaluations)} 项 criterion。"
            manual = False
        all_refs = _dedupe(
            (*base_refs, *(ref for item in evaluations for ref in item.evidence_refs))
        )
        return CompletionResult(
            status=status,
            summary=summary,
            criteria=evaluations,
            evidence_refs=all_refs or (f"completion:{goal.goal_id}:empty",),
            failed_criteria=failed,
            review_criteria=review,
            requires_manual_intervention=manual,
        )

    def _evaluate_criterion(
        self,
        criterion: SuccessCriterion,
        workdir: Path,
        *,
        evidence_refs: tuple[str, ...],
        changed_paths: tuple[str, ...],
    ) -> CriterionEvaluation:
        if criterion.kind == "manual":
            return self._evaluate_semantic(
                criterion,
                evidence_refs,
                fallback_summary="manual criterion 没有可执行的确定性检查。",
            )
        if criterion.kind == "path_changed":
            return self._evaluate_path_changed(criterion, workdir, changed_paths)

        request = VerificationRequest(
            workdir=workdir,
            required_paths=(criterion.path,)
            if criterion.kind == "path_exists"
            else (),
            content_requirements=(
                ContentRequirement(
                    path=criterion.path or "",
                    expected_text=criterion.expected_text or "",
                ),
            )
            if criterion.kind == "content_contains"
            else (),
            test_command=criterion.command if criterion.kind == "command" else None,
        )
        verification = self._deterministic_verifier.verify(request)
        refs = _dedupe(
            (
                *evidence_refs,
                f"criterion:{criterion.id}",
                *verification.evidence_refs,
            )
        )
        return CriterionEvaluation(
            criterion_id=criterion.id,
            status=verification.status,
            summary=verification.summary,
            evidence_refs=refs,
            checks=verification.checks,
        )

    @staticmethod
    def _evaluate_path_changed(
        criterion: SuccessCriterion,
        workdir: Path,
        changed_paths: tuple[str, ...],
    ) -> CriterionEvaluation:
        assert criterion.path is not None
        target = CompletionGate._normalize_path(criterion.path, workdir)
        observed = {
            CompletionGate._normalize_path(path, workdir)
            for path in changed_paths
        }
        evidence_ref = f"changed:{target}"
        if target in observed:
            status: VerificationStatus = "pass"
            summary = f"已确认目标文件发生变化：{criterion.path}。"
        elif not changed_paths:
            status = "needs_review"
            summary = f"缺少文件变更 evidence，无法确认：{criterion.path}。"
        else:
            status = "fail"
            summary = f"目标文件未出现在变更 evidence 中：{criterion.path}。"
        check = VerificationCheck(
            name=f"path_changed:{criterion.path}",
            passed=status == "pass",
            evidence_ref=evidence_ref,
            detail=summary,
        )
        return CriterionEvaluation(
            criterion_id=criterion.id,
            status=status,
            summary=summary,
            evidence_refs=(f"criterion:{criterion.id}", evidence_ref),
            checks=(check,),
        )

    def _evaluate_semantic(
        self,
        criterion: SuccessCriterion,
        evidence_refs: tuple[str, ...],
        *,
        fallback_summary: str,
    ) -> CriterionEvaluation:
        if self._semantic_verifier is None or not evidence_refs:
            return CriterionEvaluation(
                criterion_id=criterion.id,
                status="needs_review",
                summary=(
                    fallback_summary
                    + " 需要提供带 evidence 的语义 verifier 或人工复核。"
                ),
                evidence_refs=(
                    f"criterion:{criterion.id}",
                    "completion:semantic:no-evidence",
                ),
            )
        verifier = self._semantic_verifier
        if isinstance(verifier, EvidenceBackedSemanticVerifier):
            result = verifier.verify(criterion.description, evidence_refs)
        elif hasattr(verifier, "verify"):
            result = verifier.verify(criterion, evidence_refs)  # type: ignore[union-attr]
        elif callable(verifier):
            result = verifier(criterion, evidence_refs)
        else:
            raise CompletionValidationError("semantic_verifier 必须可调用或实现 verify。")
        if not isinstance(result, VerificationResult):
            raise CompletionValidationError("semantic_verifier 必须返回 VerificationResult。")
        refs = _dedupe(
            (*evidence_refs, f"criterion:{criterion.id}", *result.evidence_refs)
        )
        return CriterionEvaluation(
            criterion_id=criterion.id,
            status=result.status,
            summary=result.summary,
            evidence_refs=refs,
            checks=result.checks,
        )

    @staticmethod
    def _normalize_path(path: str, workdir: Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(workdir.resolve())
            except ValueError:
                candidate = candidate.resolve()
        return candidate.as_posix()


CompletionCriterionResult = CriterionEvaluation

__all__ = [
    "CompletionCriterionResult",
    "CompletionCriterionStatus",
    "CompletionGate",
    "CompletionReport",
    "CompletionResult",
    "CompletionStatus",
    "CompletionValidationError",
    "CriterionEvaluation",
    "SemanticCriterionEvaluator",
    "SemanticCriterionVerifier",
]
