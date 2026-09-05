import sys

from advanced_coding_agent.planning import (
    DeterministicPlanner,
    PlanExecutionState,
    PlanExecutor,
    PlanningRequest,
    StepExecution,
)
from advanced_coding_agent.verification import (
    ContentRequirement,
    DeterministicVerifier,
    EvidenceBackedSemanticVerifier,
    VerificationRequest,
    VerificationResult,
)


def build_state() -> PlanExecutionState:
    result = DeterministicPlanner().plan(
        PlanningRequest(goal="修复用户登录失败的 bug")
    )
    assert result.plan is not None
    return PlanExecutionState.create(result.plan)


def test_deterministic_verifier_checks_file_content_and_command(tmp_path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("login fixed", encoding="utf-8")
    request = VerificationRequest(
        workdir=tmp_path,
        required_paths=("result.txt",),
        content_requirements=(
            ContentRequirement(path="result.txt", expected_text="fixed"),
        ),
        test_command=(sys.executable, "-c", "raise SystemExit(0)"),
    )

    result = DeterministicVerifier().verify(request)

    assert result.status == "pass"
    assert len(result.checks) == 4


def test_failed_verification_keeps_step_out_of_completed_state() -> None:
    def verifier(_step, _execution) -> VerificationResult:
        return VerificationResult(
            status="fail",
            summary="测试失败",
            evidence_refs=("command:test-failed",),
            failed_checks=("test_command",),
        )

    state = build_state()
    PlanExecutor(verifier=lambda step, execution: verifier(step, execution)).run_next(
        state
    )

    assert state.status == "failed"
    assert state.completed_step_ids == ()
    assert state.step_results["locate-entry"].verification_status == "fail"


def test_semantic_verifier_requires_step_evidence() -> None:
    verifier = EvidenceBackedSemanticVerifier(
        evaluator=lambda _summary, _evidence: "pass"
    )

    result = verifier.verify("完成目标", ())

    assert result.status == "needs_review"


def test_empty_deterministic_checks_need_review(tmp_path) -> None:
    result = DeterministicVerifier().verify(VerificationRequest(workdir=tmp_path))

    assert result.status == "needs_review"
