"""Exercise the actual Planning Graph with local runners, never a model."""

from pathlib import Path

import pytest
from advanced_coding_agent.long_horizon.goal import SuccessCriterion
from advanced_coding_agent.planning.execution import StepExecution
from advanced_coding_agent.planning.graph import (
    create_planning_graph,
    invoke_planning_graph,
)
from advanced_coding_agent.planning.planner import DeterministicPlanner
from advanced_coding_agent.planning.replan import ReplanBudget, ReplanObservation


def run_graph(tmp_path: Path, budget: ReplanBudget, calls: list[str], after_call=None):
    (tmp_path / "goal.txt").write_text("ready")

    def runner(step, state):
        calls.append(step.id)
        if after_call is not None:
            after_call()
        return StepExecution(
            summary="Local observation",
            evidence_refs=(f"local:{step.id}",),
            tool_call_ids=(f"call:{step.id}",),
        )

    graph = create_planning_graph(
        planner=DeterministicPlanner(),
        workdir=tmp_path,
        step_runner=runner,
        budget=budget,
    )
    return invoke_planning_graph(
        graph,
        goal="修复配置并补测试",
        workdir=tmp_path,
        success_criteria=(
            SuccessCriterion("output", "path_exists", "Output exists", path="goal.txt"),
        ),
    )


def test_oversized_initial_plan_never_executes(tmp_path):
    calls = []
    result = run_graph(tmp_path, ReplanBudget(max_steps=1), calls)
    assert result["graph_status"] == "blocked"
    assert "max_steps" in result["blocked_reason"]
    assert calls == []


@pytest.mark.parametrize("limit", [0, 1])
def test_tool_budget_stops_normal_steps_without_replan(tmp_path, limit):
    calls = []
    result = run_graph(tmp_path, ReplanBudget(max_tool_calls=limit), calls)
    assert result["graph_status"] == "blocked"
    assert "tool" in result["blocked_reason"]
    assert len(calls) == limit
    assert result["tool_call_count"] == limit
    assert result["replan_count"] == 0


def test_execution_time_is_measured_and_blocks_following_steps(tmp_path, monkeypatch):
    import advanced_coding_agent.planning.graph as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def advance():
        clock[0] += 1.0

    calls = []
    result = run_graph(tmp_path, ReplanBudget(max_runtime_seconds=0.5), calls, advance)
    assert result["graph_status"] == "blocked"
    assert "runtime" in result["blocked_reason"]
    assert result["runtime_seconds"] >= 1
    assert len(calls) == 1


def test_within_budget_still_reaches_completion_gate(tmp_path):
    calls = []
    result = run_graph(tmp_path, ReplanBudget(), calls)
    assert result["graph_status"] == "completed"
    assert result["completion"]["status"] == "succeeded"
    assert result["tool_call_count"] == len(calls) > 1


def test_reactive_branch_cannot_skip_frozen_goal_criteria(tmp_path):
    graph = create_planning_graph(planner=DeterministicPlanner(), workdir=tmp_path)
    result = invoke_planning_graph(
        graph,
        goal="查找配置文件",
        workdir=tmp_path,
        success_criteria=(
            SuccessCriterion(
                "output", "path_exists", "Output exists", path="missing.txt"
            ),
        ),
    )
    assert result["graph_status"] == "blocked"
    assert result["completion"]["status"] == "failed"
    assert result["tool_call_count"] == 1


def test_reactive_branch_respects_zero_tool_budget(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("An exhausted budget must not invoke a repository tool")

    monkeypatch.setattr(
        "advanced_coding_agent.runtime.reactive.ReactiveBaseline.run", forbidden
    )
    graph = create_planning_graph(
        planner=DeterministicPlanner(),
        workdir=tmp_path,
        budget=ReplanBudget(max_tool_calls=0),
    )
    result = invoke_planning_graph(graph, goal="查找配置文件", workdir=tmp_path)
    assert result["graph_status"] == "blocked"
    assert result["tool_call_count"] == 0


def test_replan_uses_the_backend_and_stops_at_the_limit(tmp_path):
    def invalidated(step, execution, verification):
        return ReplanObservation(
            "New evidence invalidated the plan", True, ("local:changed",)
        )

    graph = create_planning_graph(
        planner=DeterministicPlanner(),
        workdir=tmp_path,
        replan_observer=invalidated,
        budget=ReplanBudget(max_replans=1),
    )
    result = invoke_planning_graph(graph, goal="修复配置并补测试", workdir=tmp_path)
    assert result["graph_status"] == "blocked"
    assert result["replan_count"] == 1
    assert len(result["replan_history"]) == 1
    assert "max_replans" in result["blocked_reason"]


def test_manual_goal_never_accepts_demo_step_verification(tmp_path):
    graph = create_planning_graph(planner=DeterministicPlanner(), workdir=tmp_path)
    result = invoke_planning_graph(graph, goal="修复配置并补测试", workdir=tmp_path)
    assert result["graph_status"] == "blocked"
    assert result["completion"]["status"] == "needs_review"


def test_checkpoint_before_completion_does_not_project_success(tmp_path):
    from advanced_coding_agent.planning.graph import initial_planning_state

    graph = create_planning_graph(planner=DeterministicPlanner(), workdir=tmp_path)
    config = {"configurable": {"thread_id": "local-before-completion"}}
    state = initial_planning_state(goal="修复配置并补测试", workdir=tmp_path)
    paused = graph.invoke(state, config=config, interrupt_before=["completion"])
    assert paused["execution_status"] == "completed"
    assert paused["run_projection"]["status"] == "running"
    resumed = graph.invoke(None, config=config)
    assert resumed["run_projection"]["status"] == "blocked"
    assert resumed["completion"]["status"] == "needs_review"


def test_completion_time_cannot_exceed_the_runtime_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import advanced_coding_agent.planning.graph as module
    from advanced_coding_agent.long_horizon.completion import CompletionGate
    from advanced_coding_agent.verification import VerificationResult

    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def verify(request):
        clock[0] += 1.0
        return VerificationResult("pass", "Local check passed", ("local:check",))

    graph = create_planning_graph(
        planner=DeterministicPlanner(),
        workdir=tmp_path,
        budget=ReplanBudget(max_runtime_seconds=0.5),
        completion_gate=CompletionGate(
            deterministic_verifier=SimpleNamespace(verify=verify)
        ),
    )
    result = invoke_planning_graph(
        graph,
        goal="修复配置并补测试",
        workdir=tmp_path,
        success_criteria=(
            SuccessCriterion("output", "path_exists", "Output exists", path="goal.txt"),
        ),
    )
    assert result["graph_status"] == "blocked"
    assert "runtime" in result["blocked_reason"]
