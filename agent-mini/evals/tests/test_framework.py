import pytest

from evals.judge import _parse_json_output, build_judge_prompt
from evals.run import discover_cases, load_case, select_cases
from src.agent.loop import RunStats


def test_target_case_matrix_is_exactly_28():
    cases = discover_cases()

    assert len(cases) == 28
    assert len(select_cases(cases, suite="core", case_names=None)) == 22
    assert len(select_cases(cases, suite="regression", case_names=None)) == 6
    assert len(select_cases(cases, suite="full", case_names=None)) == 28
    assert len(select_cases(cases, suite="all", case_names=None)) == 28

    judge_cases = [
        case_dir
        for case_dir in cases
        if load_case(case_dir / "case.yaml").eval_type == "judge"
    ]
    assert len(judge_cases) == 5
    assert load_case(
        next(
            case_dir
            for case_dir in cases
            if case_dir.name == "ambiguous_tradeoff"
        )
        / "case.yaml"
    ).eval_type == "judge"


def test_required_capability_groups_are_present():
    cases = discover_cases()
    capabilities = {
        capability
        for case_dir in cases
        for capability in load_case(case_dir / "case.yaml").capabilities
    }

    assert {
        "ambiguous_requirements",
        "prompt_injection",
        "mcp",
        "planning",
        "recovery",
        "subjective_task",
        "multi_file",
        "feature_implementation",
        "clarification",
    } <= capabilities


def test_run_stats_records_trajectory_metrics():
    stats = RunStats()

    stats.record_tool_call("spawn_subagent", {"task": "inspect"})
    stats.record_tool_call("policy__lookup_policy", {"topic": "shipping"})
    stats.record_tool_call(
        "run_shell",
        {"command": "uv run --with pytest python -m pytest -q"},
    )
    stats.record_tool_result("error", "temporary tool failure")
    stats.record_tool_result("ok", "recovered")

    assert stats.trajectory_metrics() == {
        "subagent_used": True,
        "mcp_used": True,
        "verification_command_used": True,
        "tool_call_count": 3,
        "tool_failure_count": 1,
        "recovered_after_tool_failure": True,
    }


def test_judge_prompt_uses_dimension_specific_anchors():
    prompt = build_judge_prompt(
        task="task",
        reference="reference",
        answer="answer",
    )

    assert "accuracy：5=所有关键事实和结论正确" in prompt
    assert "completeness：5=覆盖任务要求和参考事实的全部关键点" in prompt
    assert "conciseness：5=直接、结构清晰且没有无关重复" in prompt


def test_judge_parser_accepts_json_fence_and_rejects_invalid_score():
    result = _parse_json_output(
        """```json
        {"reasoning":"ok","accuracy":4,"completeness":3,"conciseness":5}
        ```"""
    )
    assert result.accuracy == 4
    assert result.completeness == 3

    with pytest.raises(ValueError):
        _parse_json_output(
            '{"reasoning":"bad","accuracy":6,"completeness":3,"conciseness":5}'
        )
