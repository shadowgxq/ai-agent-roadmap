import pytest

from evals.judge import _parse_json_output
from evals.run import discover_cases, load_case, select_cases


def test_target_case_matrix_is_exactly_28():
    cases = discover_cases()

    assert len(cases) == 28
    assert len(select_cases(cases, suite="core", case_names=None)) == 22
    assert len(select_cases(cases, suite="regression", case_names=None)) == 6
    assert len(select_cases(cases, suite="full", case_names=None)) == 28
    assert len(select_cases(cases, suite="all", case_names=None)) == 28


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
    } <= capabilities


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
