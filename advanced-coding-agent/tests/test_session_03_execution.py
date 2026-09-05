from advanced_coding_agent.planning import (
    DeterministicPlanner,
    PlanExecutionState,
    PlanExecutor,
    PlanningRequest,
    StepExecution,
)


def build_state() -> PlanExecutionState:
    result = DeterministicPlanner().plan(
        PlanningRequest(goal="修复用户登录失败的 bug")
    )
    assert result.plan is not None
    return PlanExecutionState.create(result.plan)


def test_executor_advances_one_step_at_a_time() -> None:
    state = build_state()
    executor = PlanExecutor()

    executor.run_next(state)

    assert state.status == "pending"
    assert state.current_step is None
    assert state.completed_step_ids == ("locate-entry",)


def test_checkpoint_resume_continues_the_running_step() -> None:
    state = build_state()
    running_step = state.claim_next_step()
    assert running_step is not None
    checkpoint = state.as_dict()
    restored = PlanExecutionState.from_dict(checkpoint)
    executed_ids: list[str] = []

    def runner(step, _state) -> StepExecution:
        executed_ids.append(step.id)
        return StepExecution(
            summary="恢复后继续执行",
            evidence_refs=(f"resume:{step.id}",),
        )

    PlanExecutor(runner).run_next(restored)

    assert executed_ids == [running_step.id]
    assert restored.completed_step_ids == (running_step.id,)


def test_executor_can_finish_the_serial_plan() -> None:
    state = build_state()

    PlanExecutor().run_until_finished(state)

    assert state.status == "completed"
    assert state.current_step is None
    assert state.completed_step_ids == (
        "locate-entry",
        "inspect-call-chain",
        "change-root-cause",
        "run-verification",
    )
