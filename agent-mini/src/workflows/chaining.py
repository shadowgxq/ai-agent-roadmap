from .runtime import WorkflowRuntime
from .state import WorkflowState


class WorkflowGateError(ValueError):
    """Workflow 的确定性检查未通过。"""


async def plan_step(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_tokens: int = 1000,
) -> None:
    """执行计划步骤，生成计划并更新状态。"""
    try:
        state.status = "planning"
        state.plan = await runtime.complete(
            step_name="plan",
            system_prompt=(
                "你负责把任务拆成清晰、可执行的步骤，"
                "只输出实施计划，不直接编写代码。"
            ),
            user_prompt=state.task,
            max_tokens=max_tokens,
        )
    except Exception:
        state.status = "failed"
        raise


def validate_plan(
    state: WorkflowState,
    *,
    max_chars: int = 6000,
) -> None:
    """确保计划可供后续实现步骤使用。"""
    if max_chars <= 0:
        raise ValueError("max_chars 必须大于 0")

    if not state.plan.strip():
        state.status = "failed"
        raise WorkflowGateError("计划不能为空")

    if len(state.plan) > max_chars:
        state.status = "failed"
        raise WorkflowGateError(
            f"计划长度不能超过 {max_chars} 个字符"
        )


async def implement_step(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_tokens: int = 2000,
) -> None:
    """根据已验证的计划生成代码实现。"""
    try:
        state.status = "implementing"
        state.code = await runtime.complete(
            step_name="implement",
            system_prompt=(
                "你负责根据已经确认的实施计划完成代码实现。"
                "只输出最终代码，不要重新制定计划。"
            ),
            user_prompt=(
                f"原始任务：\n{state.task}\n\n"
                f"实施计划：\n{state.plan}"
            ),
            max_tokens=max_tokens,
        )
    except Exception:
        state.status = "failed"
        raise


async def summarize_step(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_tokens: int = 800,
) -> None:
    """总结最终代码并把 Workflow 标记为完成。"""
    try:
        state.status = "summarizing"
        state.summary = await runtime.complete(
            step_name="summarize",
            system_prompt=(
                "你负责总结代码实现结果。"
                "说明完成了什么、关键实现和需要注意的事项，"
                "不要重新输出完整代码。"
            ),
            user_prompt=(
                f"原始任务：\n{state.task}\n\n"
                f"最终代码：\n{state.code}"
            ),
            max_tokens=max_tokens,
        )
        state.status = "completed"
    except Exception:
        state.status = "failed"
        raise


async def run_chaining(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    plan_max_chars: int = 6000,
) -> WorkflowState:
    """按固定顺序运行完整的 Prompt Chaining Workflow。"""
    await plan_step(runtime, state)
    validate_plan(state, max_chars=plan_max_chars)
    await implement_step(runtime, state)
    await summarize_step(runtime, state)
    return state
