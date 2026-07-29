import asyncio
import json

from pydantic import BaseModel, Field, ValidationError, field_validator

from .parallelization import ParallelResult
from .runtime import WorkflowRuntime
from .state import WorkflowState


class WorkerAssignment(BaseModel):
    """Orchestrator 为一个独立 Worker 生成的任务说明。"""

    name: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    instruction: str = Field(min_length=1)

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, value: str) -> str:
        """拒绝只有空白字符的 Worker 指令。"""
        value = value.strip()
        if not value:
            raise ValueError("Worker instruction 不能为空")
        return value


class OrchestrationPlan(BaseModel):
    """经过结构化验证的动态任务拆分结果。"""

    assignments: list[WorkerAssignment] = Field(min_length=1)
    synthesis_goal: str = Field(min_length=1)

    @field_validator("synthesis_goal")
    @classmethod
    def validate_synthesis_goal(cls, value: str) -> str:
        """拒绝只有空白字符的汇总目标。"""
        value = value.strip()
        if not value:
            raise ValueError("synthesis_goal 不能为空")
        return value


class OrchestratorState(WorkflowState):
    """Orchestrator-Workers Workflow 的计划和中间结果。"""

    orchestration_plan: OrchestrationPlan | None = None
    worker_results: list[ParallelResult] = Field(default_factory=list)


class StructuredOrchestrationError(RuntimeError):
    """Orchestrator 多次未能返回可执行的结构化计划。"""


def validate_orchestration_plan(
    plan: OrchestrationPlan,
    *,
    max_workers: int,
) -> None:
    """检查依赖运行参数、无法只靠 JSON Schema 表达的约束。"""
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")

    if len(plan.assignments) > max_workers:
        raise ValueError(
            f"Worker 数量不能超过 {max_workers}，"
            f"当前为 {len(plan.assignments)}"
        )

    names = [assignment.name for assignment in plan.assignments]
    if len(names) != len(set(names)):
        raise ValueError("Worker 名称不能重复")


async def orchestrate(
    runtime: WorkflowRuntime,
    state: OrchestratorState,
    *,
    max_workers: int = 5,
    max_tokens: int = 1200,
    max_parse_attempts: int = 2,
) -> OrchestrationPlan:
    """让模型动态拆分任务，并由 Python 验证计划边界。"""
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须大于 0")
    if max_parse_attempts <= 0:
        raise ValueError("max_parse_attempts 必须大于 0")

    state.status = "orchestrating"
    schema = json.dumps(
        OrchestrationPlan.model_json_schema(),
        ensure_ascii=False,
    )
    base_prompt = (
        f"原始任务：\n{state.task}\n\n"
        f"最多允许 {max_workers} 个 Worker。\n\n"
        f"JSON Schema：\n{schema}"
    )
    previous_output = ""
    plan_error = ""

    for attempt in range(1, max_parse_attempts + 1):
        if attempt == 1:
            user_prompt = base_prompt
        else:
            user_prompt = (
                f"{base_prompt}\n\n"
                f"上一次输出：\n{previous_output}\n\n"
                f"计划错误：\n{plan_error}\n\n"
                "请修正计划并重新输出完整 JSON。"
            )

        try:
            output = await runtime.complete(
                step_name=f"orchestrator-parse-{attempt}",
                system_prompt=(
                    "你是任务编排者，只负责把复杂任务拆成可以独立执行的子任务。"
                    "每个 assignment 必须目标明确、范围不重叠，"
                    "并包含 Worker 独立完成它所需的上下文。"
                    "不要执行原始任务，不要生成 system prompt、工具或权限配置。"
                    "简单任务应使用较少 Worker，不要为了达到上限强行拆分。"
                    "synthesis_goal 用于说明最终应如何组合全部 Worker 结果。"
                    "必须严格按照 JSON Schema 返回 JSON，"
                    "不要输出 Markdown 或其他解释。"
                ),
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
        except Exception:
            state.status = "failed"
            raise

        try:
            plan = OrchestrationPlan.model_validate_json(output)
            validate_orchestration_plan(
                plan,
                max_workers=max_workers,
            )
        except (ValidationError, ValueError) as exc:
            previous_output = output
            plan_error = str(exc)
            continue

        state.orchestration_plan = plan
        return plan

    state.status = "failed"
    raise StructuredOrchestrationError(
        f"orchestrator 连续 {max_parse_attempts} 次返回无效计划"
    )


async def run_assignment(
    runtime: WorkflowRuntime,
    state: OrchestratorState,
    assignment: WorkerAssignment,
    *,
    synthesis_goal: str,
    max_tokens: int = 1600,
) -> ParallelResult:
    """使用固定执行约束完成一个动态生成的 Worker 子任务。"""
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须大于 0")

    output = await runtime.complete(
        step_name=f"worker-{assignment.name}",
        system_prompt=(
            "你是 Orchestrator-Workers Workflow 中的执行 Worker。"
            "只完成分配给你的子任务，不重新拆分任务，"
            "不代替其他 Worker，也不编造未提供的上下文。"
            "输出应当具体、完整，并便于后续 Synthesizer 使用。"
        ),
        user_prompt=(
            f"原始任务：\n{state.task}\n\n"
            f"你的子任务：\n{assignment.instruction}\n\n"
            f"最终汇总目标：\n{synthesis_goal}"
        ),
        max_tokens=max_tokens,
    )
    return ParallelResult(
        name=assignment.name,
        output=output,
    )


async def run_assignments(
    runtime: WorkflowRuntime,
    state: OrchestratorState,
    plan: OrchestrationPlan,
    *,
    max_tokens: int = 1600,
) -> list[ParallelResult]:
    """严格模式并发执行计划中的全部 Worker 子任务。"""
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须大于 0")
    if not plan.assignments:
        raise ValueError("Worker assignments 不能为空")

    names = [assignment.name for assignment in plan.assignments]
    if len(names) != len(set(names)):
        raise ValueError("Worker 名称不能重复")

    state.status = "parallelizing"
    try:
        results = await asyncio.gather(
            *(
                run_assignment(
                    runtime,
                    state,
                    assignment,
                    synthesis_goal=plan.synthesis_goal,
                    max_tokens=max_tokens,
                )
                for assignment in plan.assignments
            )
        )
    except Exception:
        state.status = "failed"
        raise

    state.worker_results = list(results)
    return state.worker_results


def validate_worker_results(
    plan: OrchestrationPlan,
    results: list[ParallelResult],
) -> None:
    """确保每个 assignment 都有且只有一个对应结果。"""
    expected_names = [assignment.name for assignment in plan.assignments]
    actual_names = [result.name for result in results]

    if len(expected_names) != len(set(expected_names)):
        raise ValueError("计划中的 Worker 名称不能重复")
    if len(actual_names) != len(set(actual_names)):
        raise ValueError("Worker 结果名称不能重复")
    if (
        len(actual_names) != len(expected_names)
        or set(actual_names) != set(expected_names)
    ):
        missing = sorted(set(expected_names) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(expected_names))
        raise ValueError(
            "Worker 结果与计划不匹配："
            f"missing={missing}, unexpected={unexpected}"
        )
    empty_results = [
        result.name for result in results if not result.output.strip()
    ]
    if empty_results:
        raise ValueError(f"Worker 输出不能为空：{empty_results}")


async def synthesize(
    runtime: WorkflowRuntime,
    state: OrchestratorState,
    plan: OrchestrationPlan,
    results: list[ParallelResult],
    *,
    max_tokens: int = 2000,
) -> str:
    """按照计划的汇总目标整合完整的 Worker 结果。"""
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须大于 0")
    validate_worker_results(plan, results)

    assignments_by_name = {
        assignment.name: assignment.instruction
        for assignment in plan.assignments
    }
    synthesis_inputs = [
        {
            "name": result.name,
            "instruction": assignments_by_name[result.name],
            "output": result.output,
        }
        for result in results
    ]
    serialized_inputs = json.dumps(
        synthesis_inputs,
        ensure_ascii=False,
        indent=2,
    )

    state.status = "summarizing"
    try:
        return await runtime.complete(
            step_name="synthesizer",
            system_prompt=(
                "你是 Orchestrator-Workers Workflow 的结果综合者。"
                "严格按照 synthesis_goal 组合 Worker 输出，"
                "解决重复和表述冲突，形成直接回应原始任务的完整结果。"
                "只能依据提供的 Worker 输出，不要虚构新事实，"
                "不要重新拆分任务或要求 Worker 继续工作。"
            ),
            user_prompt=(
                f"原始任务：\n{state.task}\n\n"
                f"汇总目标：\n{plan.synthesis_goal}\n\n"
                f"Worker 任务与结果：\n{serialized_inputs}"
            ),
            max_tokens=max_tokens,
        )
    except Exception:
        state.status = "failed"
        raise


async def run_orchestrator_workers(
    runtime: WorkflowRuntime,
    state: OrchestratorState,
    *,
    max_workers: int = 5,
    orchestrator_max_tokens: int = 1200,
    worker_max_tokens: int = 1600,
    synthesizer_max_tokens: int = 2000,
    max_parse_attempts: int = 2,
) -> OrchestratorState:
    """动态拆分任务，并发执行 Worker，再综合最终结果。"""
    try:
        plan = await orchestrate(
            runtime,
            state,
            max_workers=max_workers,
            max_tokens=orchestrator_max_tokens,
            max_parse_attempts=max_parse_attempts,
        )
        results = await run_assignments(
            runtime,
            state,
            plan,
            max_tokens=worker_max_tokens,
        )
        state.summary = await synthesize(
            runtime,
            state,
            plan,
            results,
            max_tokens=synthesizer_max_tokens,
        )
        state.status = "completed"
        return state
    except Exception:
        state.status = "failed"
        raise
