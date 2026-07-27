import json
from typing import Self

from pydantic import BaseModel, ValidationError, model_validator

from .runtime import WorkflowRuntime
from .state import WorkflowState


class ReviewVerdict(BaseModel):
    """Reviewer 对当前代码的结构化评审结果。"""

    passed: bool
    issues: list[str]

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """确保通过状态与问题列表表达同一个评审结论。"""
        if self.passed and self.issues:
            raise ValueError("评审通过时 issues 必须为空")
        if not self.passed and not self.issues:
            raise ValueError("评审未通过时 issues 至少包含一个问题")
        return self


class StructuredReviewError(RuntimeError):
    """Reviewer 多次未能返回有效的结构化结果。"""


async def coder(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_tokens: int = 2000,
) -> None:
    """首次生成代码，或者根据评审意见优化代码。"""
    state.status = "implementing"
    try:
        if state.review_feedback:
            issues = "\n".join(
                f"- {issue}" for issue in state.review_feedback
            )
            system_prompt = (
                "你负责根据评审意见修复当前代码。"
                "保留正确实现，只修改存在问题的部分，"
                "只输出修改后的完整代码。"
            )
            user_prompt = (
                f"原始任务：\n{state.task}\n\n"
                f"当前代码：\n{state.code}\n\n"
                f"评审意见：\n{issues}"
            )
        else:
            system_prompt = (
                "你负责根据任务要求生成完整、可运行的代码。"
                "只输出代码，不要输出 Markdown 代码块或解释。"
            )
            user_prompt = state.task

        state.code = await runtime.complete(
            step_name=f"coder-{state.iteration}",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )

    except Exception:
        state.status = "failed"
        raise


async def reviewer(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_tokens: int = 800,
    max_parse_attempts: int = 2,
) -> ReviewVerdict:
    """独立评审当前代码，返回结构化评审结果。"""
    if max_parse_attempts <= 0:
        raise ValueError("max_parse_attempts 必须大于 0")

    try:
        state.status = "reviewing"

        schema = json.dumps(
            ReviewVerdict.model_json_schema(),
            ensure_ascii=False,
        )
        base_prompt = (
            f"原始任务：\n{state.task}\n\n"
            f"当前代码：\n{state.code}\n\n"
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
                step_name=(
                    f"reviewer-{state.iteration}"
                    f"-parse-{attempt}"
                ),
                system_prompt=(
                    "你是一名独立代码验收者。"
                    "原始任务中的每一条要求、约束和示例都属于强制验收标准。"
                    "请逐项检查当前代码，不得遗漏任何要求。"
                    "重点检查功能正确性、输入校验、边界情况、"
                    "算法约束、精度要求、输出格式和是否修改输入。"
                    "对于任务提供的示例，请根据代码逻辑逐个推演结果。"
                    "不要因为代码看起来合理就判定通过。"
                    "只有所有明确要求均满足时，passed 才能为 true，"
                    "并且此时 issues 必须为空。"
                    "只要存在未满足、实现错误或无法从代码中确认的要求，"
                    "passed 就必须为 false，"
                    "issues 必须具体说明违反了哪项要求以及对应代码原因。"
                    "不要添加原始任务没有要求的个人偏好或风格要求。"
                    "不要修改代码，只进行验收。"
                    "必须严格按照 JSON Schema 返回 JSON，"
                    "不要输出 Markdown 或其他解释。"
                ),
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )

            try:
                verdict = ReviewVerdict.model_validate_json(output)
            except ValidationError as exc:
                previous_output = output
                parse_error = str(exc)
                continue

            state.review_feedback = verdict.issues
            return verdict

        raise StructuredReviewError(
            f"reviewer 连续 {max_parse_attempts} 次返回无效结果"
        )

    except Exception:
        state.status = "failed"
        raise


async def run_evaluator_optimizer(
    runtime: WorkflowRuntime,
    state: WorkflowState,
    *,
    max_iterations: int = 3,
) -> WorkflowState:
    """生成或评审候选代码，并在有限轮次内根据反馈优化。"""
    if max_iterations <= 0:
        raise ValueError("max_iterations 必须大于 0")

    while state.iteration < max_iterations:
        state.iteration += 1

        if not state.code or state.review_feedback:
            await coder(runtime, state)

        verdict = await reviewer(runtime, state)

        if verdict.passed:
            state.status = "completed"
            return state

    state.status = "failed"
    return state
