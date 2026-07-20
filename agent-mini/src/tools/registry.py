"""把 Python 函数注册为模型可调用工具，并统一校验和执行。"""

from __future__ import annotations

import inspect
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, TypeAdapter


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class RegisteredTool:
    """已注册工具的定义和处理函数。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


@dataclass(frozen=True)
class ToolExecutionResult:
    """工具执行结果。"""

    content: str
    is_error: bool = False


def _parse_docstring(handler: ToolHandler) -> tuple[str, dict[str, str]]:
    """从 docstring 提取工具描述和参数描述。"""
    doc = inspect.getdoc(handler) or ""
    description_lines: list[str] = []
    argument_descriptions: dict[str, str] = {}
    in_args = False
    current_argument: str | None = None

    for raw_line in doc.splitlines():
        line = raw_line.strip()
        if line in {"Args:", "Arguments:", "Parameters:"}:
            in_args = True
            current_argument = None
            continue
        if line in {"Returns:", "Raises:", "Examples:", "Example:"}:
            in_args = False
            current_argument = None
            continue

        if not in_args:
            if line:
                description_lines.append(line)
            continue

        match = re.match(r"^(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)$", line)
        if match:
            current_argument = match.group(1)
            argument_descriptions[current_argument] = match.group(2)
        elif current_argument and line:
            argument_descriptions[current_argument] += f" {line}"

    description = " ".join(description_lines).strip() or handler.__name__
    return description, argument_descriptions


def _parameters(handler: ToolHandler) -> list[inspect.Parameter]:
    """读取可由 JSON object 传入的具名参数。"""
    parameters = list(inspect.signature(handler).parameters.values())
    unsupported = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }
    if any(parameter.kind in unsupported for parameter in parameters):
        raise TypeError("工具函数只支持普通具名参数和关键字参数")
    return parameters


def _type_hints(handler: ToolHandler) -> dict[str, Any]:
    """安全读取函数类型标注。"""
    try:
        return get_type_hints(handler)
    except (NameError, TypeError):
        return {}


def _is_model_type(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


def _schema_for(annotation: Any) -> dict[str, Any]:
    """把类型标注转成 JSON Schema。"""
    if annotation is inspect.Signature.empty or annotation is Any:
        return {}
    try:
        return TypeAdapter(annotation).json_schema()
    except Exception:
        return {}


def _build_definition(
    handler: ToolHandler,
) -> tuple[str, dict[str, Any]]:
    """生成工具描述和输入 schema。"""
    description, argument_descriptions = _parse_docstring(handler)
    print('=====_build_definition', description, argument_descriptions)
    parameters = _parameters(handler)
    type_hints = _type_hints(handler)

    # 单个 Pydantic 参数直接使用模型 schema。
    if len(parameters) == 1:
        parameter = parameters[0]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if _is_model_type(annotation):
            return description, annotation.model_json_schema()

    # 普通参数逐个生成 properties 和 required。
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in parameters:
        annotation = type_hints.get(parameter.name, parameter.annotation)
        property_schema = _schema_for(annotation)
        parameter_description = argument_descriptions.get(parameter.name)
        if parameter_description:
            property_schema["description"] = parameter_description
        properties[parameter.name] = property_schema

        if parameter.default is inspect.Signature.empty:
            required.append(parameter.name)

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = required
    return description, input_schema


def _prepare_arguments(
    handler: ToolHandler,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """校验模型输入并生成工具调用参数。"""
    signature = inspect.signature(handler)
    parameters = _parameters(handler)
    type_hints = _type_hints(handler)

    if len(parameters) == 1:
        parameter = parameters[0]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if _is_model_type(annotation):
            return {parameter.name: annotation.model_validate(input_data)}

    known_names = {parameter.name for parameter in parameters}
    unexpected = sorted(set(input_data) - known_names)
    if unexpected:
        raise TypeError(f"未知工具参数: {', '.join(unexpected)}")

    arguments: dict[str, Any] = {}
    for parameter in parameters:
        if parameter.name not in input_data:
            continue
        annotation = type_hints.get(parameter.name, parameter.annotation)
        value = input_data[parameter.name]
        if annotation is not inspect.Signature.empty and annotation is not Any:
            value = TypeAdapter(annotation).validate_python(value)
        arguments[parameter.name] = value

    signature.bind(**arguments)
    return arguments


def _serialize_result(result: Any) -> str:
    """把工具返回值转成文本。"""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


class ToolRegistry:
    """管理工具注册、schema 导出和执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        handler: ToolHandler,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> ToolHandler:
        """注册工具，缺省信息从函数定义生成。"""
        tool_name = name or handler.__name__
        if tool_name in self._tools:
            raise ValueError(f"工具已注册: {tool_name}")
        generated_description, generated_schema = _build_definition(handler)
        self._tools[tool_name] = RegisteredTool(
            name=tool_name,
            description=description or generated_description,
            input_schema=input_schema or generated_schema,
            handler=handler,
        )
        return handler

    def tool(
        self,
        handler: ToolHandler | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> ToolHandler | Callable[[ToolHandler], ToolHandler]:
        """支持 `@tool` 和 `@tool(...)` 两种装饰器写法。"""
        def decorator(function: ToolHandler) -> ToolHandler:
            return self.register(
                function,
                name=name,
                description=description,
                input_schema=input_schema,
            )

        if handler is None:
            return decorator
        return decorator(handler)

    def schemas(self) -> list[dict[str, Any]]:
        """导出 Messages API 使用的工具 schema。"""
        return [
            {
                "name": registered.name,
                "description": registered.description,
                "input_schema": deepcopy(registered.input_schema),
            }
            for registered in self._tools.values()
        ]

    async def execute_with_status(
        self,
        name: str,
        input_data: dict[str, Any],
    ) -> ToolExecutionResult:
        """执行工具；异常转成 is_error 结果供模型继续处理。"""
        try:
            if not isinstance(input_data, dict):
                raise TypeError("工具输入必须是 object")
            if name not in self._tools:
                raise KeyError(f"未注册工具: {name}")

            registered = self._tools[name]
            arguments = _prepare_arguments(registered.handler, input_data)
            result = registered.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return ToolExecutionResult(content=_serialize_result(result))
        except Exception as exc:
            return ToolExecutionResult(
                content=(
                    f"工具 {name} 执行失败: "
                    f"{type(exc).__name__}: {exc}"
                ),
                is_error=True,
            )

    async def execute(self, name: str, input_data: dict[str, Any]) -> str:
        """执行工具并返回结果文本。"""
        result = await self.execute_with_status(name, input_data)
        return result.content


# 供 @tool 和 Agent 共用的默认注册表。
registry = ToolRegistry()
tool = registry.tool


__all__ = [
    "RegisteredTool",
    "ToolExecutionResult",
    "ToolRegistry",
    "registry",
    "tool",
]
