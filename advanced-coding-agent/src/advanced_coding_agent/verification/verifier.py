"""Evidence-based step verification for W16 Session 4."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


VerificationStatus = Literal["pass", "fail", "needs_review"]


@dataclass(frozen=True)
class ContentRequirement:
    """A deterministic target-condition check for one text file."""

    path: str
    expected_text: str

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("ContentRequirement.path 不能为空。")
        if not self.expected_text:
            raise ValueError("ContentRequirement.expected_text 不能为空。")


@dataclass(frozen=True)
class VerificationRequest:
    """Checks that a coding step is expected to satisfy."""

    workdir: Path
    required_paths: tuple[str, ...] = ()
    content_requirements: tuple[ContentRequirement, ...] = ()
    test_command: tuple[str, ...] | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        workdir = Path(self.workdir).resolve()
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")
        if self.test_command is not None and not self.test_command:
            raise ValueError("test_command 不能为空数组。")
        object.__setattr__(self, "workdir", workdir)


@dataclass(frozen=True)
class VerificationCheck:
    """One bounded verification observation."""

    name: str
    passed: bool
    evidence_ref: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_ref": self.evidence_ref,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class VerificationResult:
    """Verifier output consumed by the Executor."""

    status: VerificationStatus
    summary: str
    evidence_refs: tuple[str, ...]
    failed_checks: tuple[str, ...] = ()
    checks: tuple[VerificationCheck, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ("pass", "fail", "needs_review"):
            raise ValueError("VerificationResult.status 不合法。")
        if not self.summary.strip():
            raise ValueError("VerificationResult.summary 不能为空。")
        if not self.evidence_refs:
            raise ValueError("VerificationResult 必须包含 evidence_refs。")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "failed_checks": list(self.failed_checks),
            "checks": [check.as_dict() for check in self.checks],
        }


class DeterministicVerifier:
    """Verify files, target content, and an optional command without model calls."""

    def verify(self, request: VerificationRequest) -> VerificationResult:
        checks: list[VerificationCheck] = []

        has_explicit_checks = bool(
            request.required_paths
            or request.content_requirements
            or request.test_command
        )
        if has_explicit_checks:
            checks.append(
                VerificationCheck(
                    name="workdir_exists",
                    passed=request.workdir.is_dir(),
                    evidence_ref=f"workdir:{request.workdir}",
                    detail="工作目录存在。"
                    if request.workdir.is_dir()
                    else "工作目录不存在。",
                )
            )

        for relative_path in request.required_paths:
            path = request.workdir / relative_path
            checks.append(
                VerificationCheck(
                    name=f"file_exists:{relative_path}",
                    passed=path.is_file(),
                    evidence_ref=f"file:{relative_path}",
                    detail="目标文件存在。" if path.is_file() else "目标文件不存在。",
                )
            )

        for requirement in request.content_requirements:
            path = request.workdir / requirement.path
            passed = False
            detail = "目标文件不存在。"
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError as exc:
                    detail = f"目标文件读取失败：{type(exc).__name__}。"
                else:
                    passed = requirement.expected_text in content
                    detail = (
                        "目标条件满足。" if passed else "目标条件未满足。"
                    )
            checks.append(
                VerificationCheck(
                    name=f"content:{requirement.path}",
                    passed=passed,
                    evidence_ref=f"content:{requirement.path}",
                    detail=detail,
                )
            )

        if request.test_command is not None:
            checks.append(self._run_command_check(request))

        if not checks:
            return VerificationResult(
                status="needs_review",
                summary="没有提供确定性检查条件，需要人工复核。",
                evidence_refs=("verification:no-checks",),
                failed_checks=("no-checks",),
                checks=(),
            )

        failed_checks = tuple(check.name for check in checks if not check.passed)
        evidence_refs = tuple(check.evidence_ref for check in checks)
        if failed_checks:
            return VerificationResult(
                status="fail",
                summary=f"确定性验证失败：{', '.join(failed_checks)}。",
                evidence_refs=evidence_refs,
                failed_checks=failed_checks,
                checks=tuple(checks),
            )
        return VerificationResult(
            status="pass",
            summary=f"确定性验证通过，共 {len(checks)} 项检查。",
            evidence_refs=evidence_refs,
            checks=tuple(checks),
        )

    @staticmethod
    def _run_command_check(request: VerificationRequest) -> VerificationCheck:
        assert request.test_command is not None
        command_label = " ".join(request.test_command)
        evidence_ref = f"command:{command_label}"
        try:
            completed = subprocess.run(
                list(request.test_command),
                cwd=request.workdir,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return VerificationCheck(
                name="test_command",
                passed=False,
                evidence_ref=evidence_ref,
                detail="验证命令超时。",
            )
        except OSError as exc:
            return VerificationCheck(
                name="test_command",
                passed=False,
                evidence_ref=evidence_ref,
                detail=f"验证命令无法启动：{type(exc).__name__}。",
            )

        return VerificationCheck(
            name="test_command",
            passed=completed.returncode == 0,
            evidence_ref=evidence_ref,
            detail=(
                "验证命令返回 0。"
                if completed.returncode == 0
                else f"验证命令返回 {completed.returncode}。"
            ),
        )


SemanticEvaluator = Callable[[str, tuple[str, ...]], VerificationStatus]


class EvidenceBackedSemanticVerifier:
    """Adapter for a future LLM verifier with an explicit evidence boundary."""

    def __init__(self, evaluator: SemanticEvaluator) -> None:
        self._evaluator = evaluator

    def verify(
        self,
        summary: str,
        evidence_refs: tuple[str, ...],
    ) -> VerificationResult:
        if not evidence_refs:
            return VerificationResult(
                status="needs_review",
                summary="语义验证缺少 evidence，需要人工复核。",
                evidence_refs=("semantic:no-evidence",),
                failed_checks=("evidence_refs",),
            )

        status = self._evaluator(summary, evidence_refs)
        if status not in ("pass", "fail", "needs_review"):
            raise ValueError("语义验证器只能返回 pass、fail 或 needs_review。")
        return VerificationResult(
            status=status,
            summary=f"语义验证结果：{status}。",
            evidence_refs=tuple(
                dict.fromkeys(evidence_refs + (f"semantic:{status}",))
            ),
            failed_checks=()
            if status == "pass"
            else (f"semantic:{status}",),
        )
