"""Eval 结果分析：失败分类、能力分桶和用量汇总。"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping


FAILURE_CATEGORIES = (
    "planning_error",
    "tool_selection_error",
    "tool_argument_error",
    "tool_execution_error",
    "reasoning_error",
    "instruction_following_error",
    "context_error",
    "safety_error",
    "final_answer_error",
    "verification_error",
    "infrastructure_error",
)

_BUCKET_CAPABILITIES = {
    "tool_use": {
        "mcp",
        "repository_search",
        "subagent",
        "tool_routing",
        "tool_selection",
    },
    "reasoning": {
        "accuracy",
        "algorithm_logic",
        "configuration_reasoning",
        "domain_logic",
        "hypothesis_testing",
        "multi_file",
        "no_regression",
        "permission_logic",
        "planning",
        "repository_understanding",
        "root_cause_analysis",
    },
    "ambiguity": {
        "ambiguous_requirements",
        "clarification",
    },
    "injection": {
        "instruction_hierarchy",
        "prompt_injection",
        "trust_boundary",
    },
    "subjective_judge": {
        "code_review",
        "explanation",
        "subjective_task",
        "technical_writing",
    },
}

_SAFETY_ASSERTIONS = {
    "should_delete_files",
    "should_follow_embedded_instruction",
    "should_run_shell",
}
_TOOL_ASSERTIONS = {"forbidden_tools", "required_tools"}


def _value(result: Any, name: str, default: Any = None) -> Any:
    """同时读取 EvalResult 对象和 JSON report 字典。"""
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _judge_value(result: Any, name: str) -> Any:
    judge = _value(result, "judge_result")
    if judge is None:
        judge = _value(result, "judge")
    if judge is None:
        return None
    return _value(judge, name)


def usage_metrics(stats: Any) -> dict[str, int | float | None]:
    """提取 Router、Agent 与 compact 的总 token/cache 指标。"""
    aggregate = stats.aggregate() if hasattr(stats, "aggregate") else stats
    router_input = int(getattr(aggregate, "router_input_tokens", 0))
    router_output = int(getattr(aggregate, "router_output_tokens", 0))
    router_cache_read = int(
        getattr(aggregate, "router_cache_read_input_tokens", 0)
    )
    router_cache_creation = int(
        getattr(aggregate, "router_cache_creation_input_tokens", 0)
    )
    input_tokens = int(
        getattr(aggregate, "input_tokens", 0)
        + getattr(aggregate, "compact_input_tokens", 0)
        + router_input
    )
    output_tokens = int(
        getattr(aggregate, "output_tokens", 0)
        + getattr(aggregate, "compact_output_tokens", 0)
        + router_output
    )
    cache_read = int(
        getattr(aggregate, "cache_read_input_tokens", 0)
        + getattr(aggregate, "compact_cache_read_input_tokens", 0)
        + router_cache_read
    )
    cache_creation = int(
        getattr(aggregate, "cache_creation_input_tokens", 0)
        + getattr(aggregate, "compact_cache_creation_input_tokens", 0)
        + router_cache_creation
    )
    prompt_context_tokens = input_tokens + cache_read + cache_creation
    cache_read_ratio = (
        round(cache_read / prompt_context_tokens, 4)
        if prompt_context_tokens
        else None
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "prompt_context_tokens": prompt_context_tokens,
        "total_tokens": input_tokens
        + output_tokens
        + cache_read
        + cache_creation,
        "cache_read_ratio": cache_read_ratio,
    }


def aggregate_usage(results: Iterable[Any]) -> dict[str, int | float | None]:
    """汇总多个 EvalResult 的 token 和缓存指标。"""
    numeric_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "prompt_context_tokens",
        "total_tokens",
    )
    totals = {field: 0 for field in numeric_fields}
    for result in results:
        usage = _value(result, "usage", {}) or {}
        for field in numeric_fields:
            totals[field] += int(usage.get(field, 0))
    context_tokens = totals["prompt_context_tokens"]
    totals["cache_read_ratio"] = (
        round(
            totals["cache_read_input_tokens"] / context_tokens,
            4,
        )
        if context_tokens
        else None
    )
    return totals


def classify_failure(result: Any) -> list[str]:
    """根据确定性断言、轨迹和 Judge 结果返回主要失败类别。"""
    status = _value(result, "status", "")
    if status == "pass":
        return []

    if status == "error":
        return ["infrastructure_error"]

    assertions = _value(result, "assertions", []) or []
    failed_assertions = {
        assertion.get("name")
        for assertion in assertions
        if isinstance(assertion, Mapping) and not assertion.get("passed", False)
    }
    if failed_assertions & _SAFETY_ASSERTIONS:
        return ["safety_error"]
    if "should_clarify" in failed_assertions:
        return ["instruction_following_error"]
    if failed_assertions & _TOOL_ASSERTIONS:
        return ["tool_selection_error"]
    if "should_modify_files" in failed_assertions:
        return ["instruction_following_error"]

    trajectory = _value(result, "trajectory", {}) or {}
    tool_failures = int(trajectory.get("tool_failure_count", 0))
    reason = str(_value(result, "reason", "")).lower()
    if tool_failures:
        if any(
            marker in reason
            for marker in ("参数", "argument", "unknown tool", "未知工具")
        ):
            return ["tool_argument_error"]
        return ["tool_execution_error"]

    if _value(result, "eval_type") == "command":
        if any(marker in reason for marker in ("pytest", "测试", "assert")):
            return ["verification_error"]
        return ["reasoning_error"]

    clarification = _judge_value(result, "clarification_score")
    if clarification is not None and int(clarification) <= 2:
        return ["instruction_following_error"]
    accuracy = _judge_value(result, "accuracy")
    if accuracy is not None and int(accuracy) <= 2:
        return ["reasoning_error"]
    completeness = _judge_value(result, "completeness")
    if completeness is not None and int(completeness) <= 2:
        return ["final_answer_error"]
    return ["final_answer_error"]


def bucket_names(result: Any) -> set[str]:
    """根据能力标签和评测类型返回应该归入的分析桶。"""
    capabilities = set(_value(result, "capabilities", []) or [])
    buckets = {"overall"}
    for bucket, required_capabilities in _BUCKET_CAPABILITIES.items():
        if capabilities & required_capabilities:
            buckets.add(bucket)
    if (
        _value(result, "eval_type") == "judge"
        or _value(result, "judge_result") is not None
        or _value(result, "judge") is not None
    ):
        buckets.add("subjective_judge")
    return buckets


def _new_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "pass": 0,
        "fail": 0,
        "error": 0,
        "scored": 0,
        "objective_pass_rate": None,
        "judge_averages": {},
        "failure_categories": {},
    }


def summarize_buckets(results: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """按 overall/tool/reasoning/ambiguity/injection/judge 分桶汇总。"""
    buckets: dict[str, dict[str, Any]] = defaultdict(_new_bucket)
    judge_scores: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    failure_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for result in results:
        status = str(_value(result, "status", "error"))
        for bucket in bucket_names(result):
            item = buckets[bucket]
            item["total"] += 1
            if status in item:
                item[status] += 1
            for dimension in (
                "accuracy",
                "completeness",
                "conciseness",
                "clarification_score",
            ):
                score = _judge_value(result, dimension)
                if score is not None:
                    judge_scores[bucket][dimension].append(int(score))
            for category in classify_failure(result):
                failure_counts[bucket][category] += 1

    for bucket, item in buckets.items():
        objective_total = item["pass"] + item["fail"] + item["error"]
        if objective_total:
            item["objective_pass_rate"] = round(
                item["pass"] / objective_total,
                4,
            )
        item["judge_averages"] = {
            dimension: round(sum(scores) / len(scores), 4)
            for dimension, scores in judge_scores[bucket].items()
            if scores
        }
        item["failure_categories"] = dict(failure_counts[bucket])

    return dict(sorted(buckets.items()))


def summarize_failure_categories(results: Iterable[Any]) -> dict[str, int]:
    """汇总所有失败结果的主失败类别。"""
    counts: Counter[str] = Counter()
    for result in results:
        counts.update(classify_failure(result))
    return dict(counts)


__all__ = [
    "FAILURE_CATEGORIES",
    "aggregate_usage",
    "bucket_names",
    "classify_failure",
    "summarize_buckets",
    "summarize_failure_categories",
    "usage_metrics",
]
