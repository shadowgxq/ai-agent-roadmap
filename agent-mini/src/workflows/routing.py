import json
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .runtime import WorkflowRuntime
from .state import WorkflowState


RouteName = Literal[
    "code_generation",
    "code_review",
    "bug_fix",
    "explanation",
]


class RouteDecision(BaseModel):
    """Router 返回的、经过类型约束的路由决定。"""

    route: RouteName
    reason: str = Field(min_length=1)


class RoutingState(WorkflowState):
    """Routing Workflow 在共享状态之外需要保存的路由信息。"""

    route: RouteName | None = None
    route_reason: str = ""


class StructuredRouteError(RuntimeError):
    """Router 多次未能返回有效的结构化路由结果。"""


async def router(
    runtime: WorkflowRuntime,
    state: RoutingState,
    *,
    max_tokens: int = 400,
    max_parse_attempts: int = 2,
) -> RouteDecision:
    """把任务分类到一个受 Python 限制的合法分支。"""
    if max_parse_attempts <= 0:
        raise ValueError("max_parse_attempts 必须大于 0")

    state.status = "routing"
    schema = json.dumps(
        RouteDecision.model_json_schema(),
        ensure_ascii=False,
    )
    base_prompt = (
        f"待分类任务：\n{state.task}\n\n"
        f"JSON Schema：\n{schema}"
    )
    previous_output = ""
    parse_error = ""

    for attempt in range(1, max_parse_attempts + 1):
        if attempt == 1:
            user_prompt = base_prompt
        else:
            user_prompt = (
                f"{base_prompt}\n\n"
                f"上一次输出：\n{previous_output}\n\n"
                f"解析错误：\n{parse_error}\n\n"
                "请修正格式并重新输出完整 JSON。"
            )

        output = await runtime.complete(
            step_name=f"router-parse-{attempt}",
            system_prompt=(
                "你是任务路由器，只负责判断用户任务的主要意图。"
                "code_generation 表示从需求生成新代码；"
                "code_review 表示只检查现有代码并提出问题；"
                "bug_fix 表示定位并修复已有代码中的问题；"
                "explanation 表示解释概念、代码或技术原理。"
                "当任务同时包含多个动作时，选择最能代表最终交付目标的路线。"
                "必须严格按照 JSON Schema 返回 JSON，"
                "不要执行任务，也不要输出 Markdown 或额外解释。"
            ),
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )

        try:
            decision = RouteDecision.model_validate_json(output)
        except ValidationError as exc:
            previous_output = output
            parse_error = str(exc)
            continue

        state.route = decision.route
        state.route_reason = decision.reason
        return decision

    state.status = "failed"
    raise StructuredRouteError(
        f"router 连续 {max_parse_attempts} 次返回无效结果"
    )


async def handle_code_generation(
    runtime: WorkflowRuntime,
    state: RoutingState,
) -> None:
    """根据需求生成新代码，并把结果保存到 code。"""
    state.status = "implementing"
    state.code = await runtime.complete(
        step_name="code-generation",
        system_prompt=(
            "你负责根据用户需求生成完整、可运行的代码。"
            "只完成任务要求，不进行代码评审或额外解释。"
        ),
        user_prompt=state.task,
        max_tokens=2000,
    )


async def handle_code_review(
    runtime: WorkflowRuntime,
    state: RoutingState,
) -> None:
    """只评审任务中提供的代码，并把意见保存到 summary。"""
    state.status = "reviewing"
    state.summary = await runtime.complete(
        step_name="code-review",
        system_prompt=(
            "你是独立代码评审者。检查正确性、边界情况和完整性，"
            "给出具体问题和原因；不要修改或重写代码。"
        ),
        user_prompt=state.task,
        max_tokens=1200,
    )


async def handle_bug_fix(
    runtime: WorkflowRuntime,
    state: RoutingState,
) -> None:
    """根据问题描述修复已有代码，并把结果保存到 code。"""
    state.status = "implementing"
    state.code = await runtime.complete(
        step_name="bug-fix",
        system_prompt=(
            "你负责定位并修复用户提供的代码问题。"
            "保留正确行为，只输出修复后的完整代码。"
        ),
        user_prompt=state.task,
        max_tokens=2000,
    )


async def handle_explanation(
    runtime: WorkflowRuntime,
    state: RoutingState,
) -> None:
    """解释技术问题，并把回答保存到 summary。"""
    state.status = "summarizing"
    state.summary = await runtime.complete(
        step_name="explanation",
        system_prompt=(
            "你负责清晰、准确地解释代码和技术概念。"
            "围绕用户问题回答，不生成无关实现。"
        ),
        user_prompt=state.task,
        max_tokens=1200,
    )


RouteHandler = Callable[
    [WorkflowRuntime, RoutingState],
    Awaitable[None],
]


ROUTE_HANDLERS: dict[RouteName, RouteHandler] = {
    "code_generation": handle_code_generation,
    "code_review": handle_code_review,
    "bug_fix": handle_bug_fix,
    "explanation": handle_explanation,
}


async def run_routing(
    runtime: WorkflowRuntime,
    state: RoutingState,
    *,
    max_parse_attempts: int = 2,
) -> RoutingState:
    """先让模型分类，再由 Python 执行与 route 对应的固定 handler。"""
    try:
        decision = await router(
            runtime,
            state,
            max_parse_attempts=max_parse_attempts,
        )
        handler = ROUTE_HANDLERS.get(decision.route)
        if handler is None:
            raise RuntimeError(f"未注册的 route: {decision.route}")

        await handler(runtime, state)
        state.status = "completed"
        return state
    except Exception:
        state.status = "failed"
        raise
