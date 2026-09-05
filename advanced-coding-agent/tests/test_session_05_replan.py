from advanced_coding_agent.planning import (
    DeterministicPlanner,
    PlanExecutionState,
    PlanExecutor,
    PlanningRequest,
    ReplanBudget,
    ReplanController,
    ReplanObservation,
    ReplanState,
)


def build_plan():
    result = DeterministicPlanner().plan(
        PlanningRequest(goal="修复用户登录失败的 bug")
    )
    assert result.plan is not None
    return result.plan


def invalidated_observation() -> ReplanObservation:
    return ReplanObservation(
        summary="根因不在原计划假设的认证入口文件中。",
        plan_invalidated=True,
        evidence_refs=("trace:root-cause-outside-entry",),
        affected_step_ids=("inspect-call-chain", "change-root-cause"),
        tool_calls_delta=1,
        runtime_seconds_delta=2.0,
    )


def test_valid_plan_does_not_trigger_meaningless_replan() -> None:
    state = ReplanState.create(build_plan())
    observation = ReplanObservation(
        summary="入口文件与原计划一致。",
        plan_invalidated=False,
        evidence_refs=("trace:entry-confirmed",),
    )

    result = ReplanController().consider(state, observation)

    assert result.decision == "unchanged"
    assert state.replan_count == 0
    assert not state.history


def test_invalidated_plan_creates_new_version_and_preserves_facts() -> None:
    execution_state = PlanExecutionState.create(build_plan())
    PlanExecutor().run_next(execution_state)
    state = ReplanState.create(execution_state.plan)

    result = ReplanController().consider(state, invalidated_observation())

    assert result.decision == "replanned"
    assert result.plan.version == 2
    assert state.replan_count == 1
    assert len(state.history) == 1
    assert state.plan.steps[0].status == "completed"
    assert state.plan.steps[1].status == "pending"


def test_replan_limit_blocks_after_budget_is_exhausted() -> None:
    state = ReplanState.create(build_plan(), ReplanBudget(max_replans=1))
    controller = ReplanController()

    first = controller.consider(state, invalidated_observation())
    second = controller.consider(state, invalidated_observation())

    assert first.decision == "replanned"
    assert second.decision == "blocked"
    assert state.status == "blocked"
    assert state.replan_count == 1


def test_tool_budget_can_block_without_replanning() -> None:
    state = ReplanState.create(build_plan(), ReplanBudget(max_tool_calls=1))
    observation = ReplanObservation(
        summary="一次工具调用已完成，计划仍然有效。",
        plan_invalidated=False,
        evidence_refs=("tool:search",),
        tool_calls_delta=2,
    )

    result = ReplanController().consider(state, observation)

    assert result.decision == "blocked"
    assert state.status == "blocked"
