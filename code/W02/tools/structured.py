from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Literal, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, ValidationError

from agent_sdk import (
    extract_assistant_blocks,
    extract_text,
    get_async_client,
    load_config,
)


ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """模型多次输出不符合 schema 时抛出的异常。"""


class RecipeInfo(BaseModel):
    """用于演示结构化输出的菜谱模型。"""

    name: str
    minutes: int
    difficulty: Literal["easy", "medium", "hard"]
    ingredients: list[str]


class StrictRecipeInfo(RecipeInfo):
    """增加约束的菜谱模型，用于观察校验失败和重试。"""

    minutes: int = Field(gt=0, multiple_of=5)
    ingredients: list[str] = Field(min_length=3)
    recipe_code: str = Field(pattern=r"^RECIPE-[0-9]{4}$")


def _schema_text(schema_model: type[BaseModel]) -> str:
    """把 Pydantic 模型的 JSON Schema 转成提示词文本。"""
    return json.dumps(
        schema_model.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def _error_summary(error: ValidationError, limit: int = 300) -> str:
    """压缩校验错误，方便打印到终端而不隐藏完整错误。"""
    summary = " ".join(str(error).split())
    if len(summary) <= limit:
        return summary
    return f"{summary[:limit]}..."


def _json_user_prompt(text: str, schema_model: type[BaseModel]) -> str:
    """生成要求模型只返回 JSON 的用户提示词。"""
    return (
        "请从下面的文本中提取结构化信息。\n"
        "只返回一个符合 JSON Schema 的 JSON object，"
        "不要输出 Markdown、代码围栏或解释文字。\n\n"
        f"JSON Schema:\n{_schema_text(schema_model)}\n\n"
        f"原始文本:\n{text}"
    )


async def extract(
    text: str,
    schema_model: type[ModelT],
    max_retries: int = 3,
    *,
    client: AsyncAnthropic,
    model: str,
    max_tokens: int = 1000,
) -> ModelT:
    """请求模型输出 JSON，并在 Pydantic 校验失败后要求模型重试。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能小于 0")

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": _json_user_prompt(text, schema_model),
        }
    ]

    for attempt in range(max_retries + 1):
        response = await client.messages.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            # 结构化抽取不需要 Thinking，且可以避免多轮校验时混入 thinking block。
            thinking={"type": "disabled"},
        )
        messages.append(
            {
                "role": "assistant",
                "content": extract_assistant_blocks(response),
            }
        )

        raw_text = extract_text(response).strip()
        print(f"[structured-json] attempt={attempt + 1}")

        try:
            result = schema_model.model_validate_json(raw_text)
            print("[structured-json] validation=success")
            return result
        except ValidationError as exc:
            if attempt == max_retries:
                raise StructuredOutputError(
                    f"结构化输出连续失败 {max_retries + 1} 次:\n{exc}"
                ) from exc

            retry_number = attempt + 1
            print(
                f"[structured-json] retry={retry_number}/{max_retries} "
                f"reason={_error_summary(exc)}"
            )

            # 把完整 ValidationError 发回模型，摘要只用于终端观测。
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "你上一次输出没有通过校验。请根据完整错误修正，"
                        "只返回新的 JSON object。\n\n"
                        f"完整 ValidationError:\n{exc}"
                    ),
                }
            )

    raise StructuredOutputError("结构化输出循环异常结束")


def _submit_result_tool(schema_model: type[BaseModel]) -> dict[str, Any]:
    """创建 input_schema 等于目标 Pydantic 模型的 submit_result 工具。"""
    return {
        "name": "submit_result",
        "description": "提交已经提取完成的结构化结果。",
        "input_schema": schema_model.model_json_schema(),
    }


def _tool_retry_message(error: ValidationError) -> str:
    """生成发送给 submit_result 工具调用的错误结果文本。"""
    return (
        "submit_result 的 input 没有通过校验，请根据错误修正后重新调用。\n"
        f"完整 ValidationError:\n{error}"
    )


async def extract_with_tool(
    text: str,
    schema_model: type[ModelT],
    max_retries: int = 3,
    *,
    client: AsyncAnthropic,
    model: str,
    max_tokens: int = 1000,
) -> ModelT:
    """强制模型调用 submit_result，并校验它传入的结构化参数。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能小于 0")

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "请从下面的文本中提取结构化信息，"
                "必须调用 submit_result 提交结果。\n\n"
                f"目标 JSON Schema:\n{_schema_text(schema_model)}\n\n"
                f"原始文本:\n{text}"
            ),
        }
    ]
    tools = [_submit_result_tool(schema_model)]

    for attempt in range(max_retries + 1):
        response = await client.messages.create(
            model=model,
            messages=messages,
            tools=tools,
            # DeepSeek 的 Thinking mode 不支持强制 tool_choice。
            # 这里显式关闭 Thinking，才能使用下面的强制 submit_result。
            thinking={"type": "disabled"},
            tool_choice={"type": "tool", "name": "submit_result"},
            max_tokens=max_tokens,
        )
        messages.append(
            {
                "role": "assistant",
                "content": extract_assistant_blocks(response),
            }
        )

        tool_use_blocks = [
            block
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "submit_result"
        ]
        print(f"[structured-tool] attempt={attempt + 1}")

        if not tool_use_blocks:
            error_text = "模型没有调用 submit_result"
            if attempt == max_retries:
                raise StructuredOutputError(
                    f"结构化工具调用连续失败 {max_retries + 1} 次: {error_text}"
                )

            retry_number = attempt + 1
            print(
                f"[structured-tool] retry={retry_number}/{max_retries} "
                f"reason={error_text}"
            )
            messages.append(
                {
                    "role": "user",
                    "content": "必须调用 submit_result，不能直接输出普通文本。",
                }
            )
            continue

        tool_use = tool_use_blocks[0]
        try:
            result = schema_model.model_validate(tool_use.input)
            print("[structured-tool] validation=success")
            return result
        except ValidationError as exc:
            if attempt == max_retries:
                raise StructuredOutputError(
                    f"submit_result 连续失败 {max_retries + 1} 次:\n{exc}"
                ) from exc

            retry_number = attempt + 1
            print(
                f"[structured-tool] retry={retry_number}/{max_retries} "
                f"reason={_error_summary(exc)}"
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": _tool_retry_message(exc),
                            "is_error": True,
                        }
                    ],
                }
            )

    raise StructuredOutputError("结构化工具调用循环异常结束")


async def main() -> None:
    """运行两种结构化输出方式的最小对照示例。"""
    config = load_config()
    use_strict_schema = "--strict" in sys.argv[1:]
    user_arguments = [
        argument
        for argument in sys.argv[1:]
        if argument != "--strict"
    ]
    schema_model = StrictRecipeInfo if use_strict_schema else RecipeInfo
    recipe_text = (
        "番茄炒蛋：准备 3 个鸡蛋、2 个番茄和少量盐。"
        "先炒鸡蛋，再加入番茄翻炒，最后加盐调味，约 15 分钟完成，难度简单。"
    )
    if user_arguments:
        recipe_text = " ".join(user_arguments)

    async with get_async_client(config) as client:
        json_result = await extract(
            recipe_text,
            schema_model,
            client=client,
            model=config.model,
        )
        tool_result = await extract_with_tool(
            recipe_text,
            schema_model,
            client=client,
            model=config.model,
        )

    print("\n=== JSON Result ===")
    print(json_result.model_dump_json(indent=2, ensure_ascii=False))
    print("\n=== Tool Result ===")
    print(tool_result.model_dump_json(indent=2, ensure_ascii=False))


__all__ = [
    "RecipeInfo",
    "StrictRecipeInfo",
    "StructuredOutputError",
    "extract",
    "extract_with_tool",
]


if __name__ == "__main__":
    asyncio.run(main())
