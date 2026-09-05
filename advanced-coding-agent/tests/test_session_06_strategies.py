from pathlib import Path

from advanced_coding_agent.cli import load_cases
from advanced_coding_agent.planning import compare_strategies


def test_strategy_comparison_reports_all_fixed_cases() -> None:
    case_file = (
        Path(__file__).parents[1] / "evals" / "cases" / "session_02.json"
    )
    cases = load_cases(case_file)

    report = compare_strategies(cases)

    assert {case.scenario for case in cases} == {
        "normal",
        "verification_failure",
        "replan",
    }
    assert len(report.runs) == 30
    assert report.recommendation == "planner-executor"
    assert all(run.success for run in report.runs)
    assert report.summary()["planner-executor"]["avg_plan_generation_count"] == 0.6
    assert report.summary()["stepwise"]["avg_plan_generation_count"] == 2.4
    assert report.summary()["planner-executor"]["checkpointable_rate"] == 0.6
