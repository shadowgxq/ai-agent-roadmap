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
    """注册表内部保存的工具定义。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


@dataclass(frozen=True)
class ToolExecutionResult:
    """统一表示工具执行结果及错误状态。"""

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
    """返回工具支持的具名参数，并拒绝不适合 JSON 输入的签名。"""
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
    try:
        return get_type_hints(handler)
    except (NameError, TypeError):
        return {}


def _is_model_type(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


def _schema_for(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Signature.empty or annotation is Any:
        return {}
    try:
        return TypeAdapter(annotation).json_schema()
    except Exception:
        return {}


def _build_definition(
    handler: ToolHandler,
) -> tuple[str, dict[str, Any]]:
    """根据函数签名、类型标注和 docstring 生成工具定义。"""
    description, argument_descriptions = _parse_docstring(handler)
    print('=====_build_definition', description, argument_descriptions)
    parameters = _parameters(handler)
    type_hints = _type_hints(handler)

    if len(parameters) == 1:
        parameter = parameters[0]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if _is_model_type(annotation):
            return description, annotation.model_json_schema()

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
    """校验模型提供的输入并转换为工具函数参数。"""
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
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


class ToolRegistry:
    """注册工具、导出 API schema，并统一执行工具。"""

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
        """注册函数；缺省的描述和 schema 会从函数定义中生成。"""
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
        """返回 `@tool` 装饰器。"""
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
        """返回可以直接传给 Messages API 的工具 schema。"""
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
        """执行工具，并把普通返回值和异常统一成结构化结果。"""
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
        """执行工具并返回可直接放入 tool_result 的文本。"""
        result = await self.execute_with_status(name, input_data)
        return result.content


registry = ToolRegistry()
tool = registry.tool


__all__ = [
    "RegisteredTool",
    "ToolExecutionResult",
    "ToolRegistry",
    "registry",
    "tool",
]
