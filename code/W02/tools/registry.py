from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
import types
from dataclasses import dataclass
from typing import Any, Callable, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, TypeAdapter


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


@dataclass(frozen=True)
class ToolExecutionResult:
    """保存工具执行后的文本结果和错误状态。"""

    content: str
    is_error: bool = False


def _parse_docstring(handler: ToolHandler) -> tuple[str, dict[str, str]]:
    """读取函数 docstring，返回工具描述和每个参数的说明。"""
    doc = inspect.getdoc(handler) or ""
    if not doc:
        return handler.__name__, {}

    lines = doc.splitlines()
    description_lines: list[str] = []
    argument_descriptions: dict[str, str] = {}
    in_args = False
    current_argument: str | None = None
    section_names = {"Returns:", "Raises:", "Examples:", "Example:"}

    for raw_line in lines:
        line = raw_line.strip()
        if line in {"Args:", "Arguments:", "Parameters:"}:
            in_args = True
            continue
        if line in section_names:
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


def _is_optional(annotation: Any) -> bool:
    """判断一个类型标注是否允许传入 None。"""
    origin = get_origin(annotation)
    return origin in {Union, types.UnionType} and type(None) in get_args(annotation)


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    """把 Python 类型标注转换成 JSON Schema 片段。"""
    if annotation is inspect.Signature.empty or annotation is Any:
        return {}

    if get_origin(annotation) is Literal:
        values = list(get_args(annotation))
        schema: dict[str, Any] = {"enum": values}
        if values and all(isinstance(value, str) for value in values):
            schema["type"] = "string"
        elif values and all(isinstance(value, bool) for value in values):
            schema["type"] = "boolean"
        elif values and all(isinstance(value, int) for value in values):
            schema["type"] = "integer"
        return schema

    try:
        return TypeAdapter(annotation).json_schema()
    except Exception:
        return {}


def _build_input_schema(handler: ToolHandler) -> tuple[str, dict[str, Any]]:
    """根据函数签名和 docstring 生成工具描述与输入 schema。"""
    description, argument_descriptions = _parse_docstring(handler)
    signature = inspect.signature(handler)
    try:
        type_hints = get_type_hints(handler)
    except (NameError, TypeError):
        type_hints = {}

    parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
    ]

    # 一个 BaseModel 参数通常代表整组工具入参，直接展开为顶层 schema。
    if len(parameters) == 1:
        parameter = parameters[0]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            return description, annotation.model_json_schema()

    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in parameters:
        annotation = type_hints.get(parameter.name, parameter.annotation)
        property_schema = _annotation_schema(annotation)
        property_description = argument_descriptions.get(parameter.name)
        if property_description:
            property_schema["description"] = property_description
        properties[parameter.name] = property_schema

        has_default = parameter.default is not inspect.Signature.empty
        if not has_default and not _is_optional(annotation):
            required.append(parameter.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return description, schema


def _is_model_type(annotation: Any) -> bool:
    """判断类型标注是否是 Pydantic BaseModel 子类。"""
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


def _prepare_arguments(handler: ToolHandler, input_data: dict[str, Any]) -> dict[str, Any]:
    """把模型传入的字典整理成函数可以接收的关键字参数。"""
    signature = inspect.signature(handler)
    try:
        type_hints = get_type_hints(handler)
    except (NameError, TypeError):
        type_hints = {}

    parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
    ]

    if len(parameters) == 1:
        parameter = parameters[0]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if _is_model_type(annotation):
            return {parameter.name: annotation.model_validate(input_data)}

    arguments: dict[str, Any] = {}
    for parameter in parameters:
        if parameter.name not in input_data:
            continue

        value = input_data[parameter.name]
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if _is_model_type(annotation):
            value = annotation.model_validate(value)
        arguments[parameter.name] = value
    return arguments


def _serialize_result(result: Any) -> str:
    """把工具返回值统一转换成可以放进 tool_result 的字符串。"""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


class ToolRegistry:
    """保存工具定义，并提供 schema 导出和工具执行能力。"""

    def __init__(self) -> None:
        """创建一个空的工具注册表。"""
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, handler: ToolHandler, *, name: str | None = None) -> ToolHandler:
        """注册一个函数，并为它生成 API 所需的工具元数据。"""
        tool_name = name or handler.__name__
        if tool_name in self._tools:
            raise ValueError(f"工具已注册: {tool_name}")

        description, input_schema = _build_input_schema(handler)
        self._tools[tool_name] = RegisteredTool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        return handler

    def tool(
        self,
        handler: ToolHandler | None = None,
        *,
        name: str | None = None,
    ) -> ToolHandler | Callable[[ToolHandler], ToolHandler]:
        """返回装饰器，让函数可以通过 @tool 自动完成注册。"""
        def decorator(function: ToolHandler) -> ToolHandler:
            """接收被装饰的函数，并交给注册表保存。"""
            return self.register(function, name=name)

        if handler is None:
            return decorator
        return decorator(handler)

    def schemas(self) -> list[dict[str, Any]]:
        """返回可以直接传给 API tools 参数的 schema 列表。"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def execute_with_status(
        self,
        name: str,
        input_data: dict[str, Any],
    ) -> ToolExecutionResult:
        """执行工具并同时返回结果文本和是否出错。"""
        try:
            if not isinstance(input_data, dict):
                raise TypeError("工具输入必须是 object")

            registered_tool = self._tools[name]
            arguments = _prepare_arguments(registered_tool.handler, input_data)
            result = registered_tool.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return ToolExecutionResult(content=_serialize_result(result))
        except Exception as exc:
            return ToolExecutionResult(
                content=f"工具 {name} 执行失败: {type(exc).__name__}: {exc}",
                is_error=True,
            )

    async def execute(self, name: str, input_data: dict[str, Any]) -> str:
        """根据工具名称执行函数，并兼容返回纯字符串的旧调用方式。"""
        execution = await self.execute_with_status(name, input_data)
        return execution.content


registry = ToolRegistry()
tool = registry.tool


@tool
async def get_weather(city: str) -> dict[str, Any]:
    """返回指定城市的本地 mock 天气，不访问真实天气服务。

    Args:
        city: 城市名称，例如北京、上海、深圳。
    """
    # 用异步延迟模拟网络 I/O，方便观察多个天气查询的并发效果。
    await asyncio.sleep(2)
    fake_weather = {
        "北京": {"temperature": 26, "condition": "晴"},
        "上海": {"temperature": 24, "condition": "多云"},
        "深圳": {"temperature": 28, "condition": "小雨"},
    }
    return {
        "city": city,
        **fake_weather.get(city, {"temperature": 25, "condition": "未知"}),
        "source": "local-mock",
    }


_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.UAdd,
    ast.USub,
)


@tool
def calculate(expression: str) -> dict[str, Any]:
    """使用受限表达式计算器执行数字四则运算。

    Args:
        expression: 数字、括号以及 +、-、*、/ 组成的表达式。
    """
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError("只支持数字和四则运算")
        if isinstance(node, ast.Constant) and type(node.value) not in {int, float}:
            raise ValueError("表达式只能包含数字")

    result = eval(compile(tree, "<calculator>", "eval"),
                  {"__builtins__": {}}, {})
    return {"expression": expression, "result": result, "source": "local-mock"}


@tool
def get_time(timezone: str) -> dict[str, Any]:
    """返回指定时区的本地 mock 时间，不访问真实时间服务。

    Args:
        timezone: 时区名称，例如 Asia/Shanghai、UTC、America/New_York。
    """
    fake_times = {
        "Asia/Shanghai": "2026-07-13 12:00:00",
        "UTC": "2026-07-13 04:00:00",
        "America/New_York": "2026-07-13 00:00:00",
    }
    return {
        "timezone": timezone,
        "time": fake_times.get(timezone, "2026-07-13 12:00:00"),
        "source": "local-mock",
    }


__all__ = [
    "ToolRegistry",
    "ToolExecutionResult",
    "calculate",
    "get_time",
    "get_weather",
    "registry",
    "tool",
]
