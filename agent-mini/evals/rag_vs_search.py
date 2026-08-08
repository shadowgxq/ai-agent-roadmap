"""对比 RAG 与 agentic search 的代码问答表现。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import yaml

from src.agent.config import AgentSettings, PROJECT_ROOT
from src.agent.cost import estimate_cost
from src.agent.loop import CostLimitExceeded, MaxTurnsExceeded, RunStats
from src.agent.runtime import ToolMode, run_coding_agent
from src.rag.indexer import load_index


CASES_PATH = Path(__file__).with_name("rag_search_cases.yaml")
ExperimentMode = Literal["rag", "search"]


@dataclass(frozen=True)
class SearchCase:
    """一个需要从代码库中定位证据的固定问题。"""

    case_id: str
    question: str
    expected_groups: list[list[str]]


@dataclass
class CaseResult:
    """一次模型运行的可比较结果。"""

    mode: ExperimentMode
    case_id: str
    status: Literal["pass", "fail", "error"]
    turns: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_s: float
    cost_usd: float | None
    tool_calls: list[str]
    matched_groups: int
    expected_groups: int
    missing_groups: list[list[str]]
    answer: str
    error: str = ""


def parse_args() -> argparse.Namespace:
    """解析对照实验参数。"""
    parser = argparse.ArgumentParser(
        description="对比 RAG 与 grep/read_file 代码搜索能力。"
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=PROJECT_ROOT,
        help="待分析代码库，默认是 agent-mini。",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=CASES_PATH,
        help="固定问题集 YAML 路径。",
    )
    parser.add_argument(
        "--mode",
        choices=("both", "rag", "search"),
        default="both",
        help="运行 RAG、agentic search 或两组都运行。",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=12,
        help="每个问题的最大 Agent 轮数。",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2_000,
        help="每次模型响应的最大输出 token 数。",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=None,
        help="单个问题的费用上限；不传则使用配置价格统计。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可选的 JSON 结果输出路径。",
    )
    parser.add_argument(
        "--show-answers",
        action="store_true",
        help="在汇总表后打印每个问题的模型回答。",
    )
    args = parser.parse_args()
    if args.max_turns < 1:
        parser.error("--max-turns 必须大于 0")
    if args.max_tokens < 1:
        parser.error("--max-tokens 必须大于 0")
    if args.max_cost_usd is not None and args.max_cost_usd <= 0:
        parser.error("--max-cost-usd 必须大于 0")
    return args


def load_cases(path: Path) -> list[SearchCase]:
    """读取并校验固定问题集。"""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"问题集必须是非空 YAML 列表: {path}")

    cases: list[SearchCase] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("问题集中的每一项必须是 object")
        case_id = str(item.get("id", "")).strip()
        question = str(item.get("question", "")).strip()
        expected_groups = item.get("expected_groups")
        if not case_id or not question:
            raise ValueError("问题项必须包含非空 id 和 question")
        if case_id in seen_ids:
            raise ValueError(f"问题 id 重复: {case_id}")
        if not isinstance(expected_groups, list) or not expected_groups:
            raise ValueError(f"问题缺少 expected_groups: {case_id}")

        normalized_groups: list[list[str]] = []
        for group in expected_groups:
            if not isinstance(group, list) or not group:
                raise ValueError(f"expected_groups 格式错误: {case_id}")
            keywords = [str(keyword).strip() for keyword in group]
            if any(not keyword for keyword in keywords):
                raise ValueError(f"expected_groups 存在空关键词: {case_id}")
            normalized_groups.append(keywords)

        cases.append(
            SearchCase(
                case_id=case_id,
                question=question,
                expected_groups=normalized_groups,
            )
        )
        seen_ids.add(case_id)
    return cases


def build_task(case: SearchCase, mode: ExperimentMode) -> str:
    """为两组实验生成相同约束、不同工具模式的任务。"""
    tool_hint = (
        "只能使用 rag_search 工具"
        if mode == "rag"
        else "只能使用 grep 和 read_file 工具"
    )
    return f"""
你正在参加代码搜索对照实验。本次{tool_hint}，不要调用其他工具，也不要凭记忆猜测。

问题：{case.question}

回答要求：
1. 先使用可用工具查找证据；
2. 最终回答必须列出文件路径、函数或类名称，以及简短调用链；
3. 如果工具结果不足以确认结论，必须明确说明证据不足。
""".strip()


def normalize_text(value: str) -> str:
    """统一答案中的路径分隔符和大小写，便于做最小证据检查。"""
    return value.lower().replace("\\", "/")


def missing_groups(
    answer: str,
    expected_groups: list[list[str]],
) -> list[list[str]]:
    """返回未被答案完整覆盖的证据关键词组。"""
    normalized_answer = normalize_text(answer)
    return [
        group
        for group in expected_groups
        if not all(
            normalize_text(keyword) in normalized_answer
            for keyword in group
        )
    ]


async def run_case(
    case: SearchCase,
    mode: ExperimentMode,
    *,
    workdir: Path,
    settings: AgentSettings,
    max_turns: int,
    max_tokens: int,
    max_cost_usd: float | None,
) -> CaseResult:
    """运行一个问题并提取统一指标。"""
    started_at = perf_counter()
    tool_calls: list[str] = []
    stats = RunStats()
    answer = ""
    error = ""

    async def collect_event(event: str, data: dict[str, Any]) -> None:
        if event != "tool_call":
            return
        for call in data.get("calls", []):
            if isinstance(call, dict) and isinstance(call.get("name"), str):
                tool_calls.append(call["name"])

    try:
        response, stats = await run_coding_agent(
            task=build_task(case, mode),
            workdir=workdir,
            settings=settings,
            max_turns=max_turns,
            max_tokens=max_tokens,
            max_cost_usd=max_cost_usd,
            run_id=f"session6-{mode}-{case.case_id}-{uuid4().hex[:8]}",
            enable_subagent=False,
            tool_mode=mode,
            checkpoint_enabled=False,
            event_callback=collect_event,
        )
        answer = response.choices[0].message.content or ""
        missing = missing_groups(answer, case.expected_groups)
        status: Literal["pass", "fail", "error"] = (
            "pass" if not missing else "fail"
        )
    except MaxTurnsExceeded as exc:
        stats = exc.stats
        missing = case.expected_groups
        status = "fail"
        error = str(exc)
    except CostLimitExceeded as exc:
        stats = exc.stats
        missing = case.expected_groups
        status = "error"
        error = str(exc)
    except Exception as exc:
        missing = case.expected_groups
        status = "error"
        error = f"{type(exc).__name__}: {exc}"

    matched = len(case.expected_groups) - len(missing)
    return CaseResult(
        mode=mode,
        case_id=case.case_id,
        status=status,
        turns=stats.turns,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        total_tokens=stats.total_tokens,
        duration_s=perf_counter() - started_at,
        cost_usd=estimate_cost(stats, settings),
        tool_calls=tool_calls,
        matched_groups=matched,
        expected_groups=len(case.expected_groups),
        missing_groups=missing,
        answer=answer,
        error=error,
    )


def format_cost(value: float | None) -> str:
    """格式化可选费用。"""
    return "n/a" if value is None else f"${value:.6f}"


def print_result(result: CaseResult) -> None:
    """打印单题结果摘要。"""
    tools = ",".join(dict.fromkeys(result.tool_calls)) or "-"
    print(
        f"[{result.mode:6}] {result.case_id:24} "
        f"status={result.status:5} "
        f"evidence={result.matched_groups}/{result.expected_groups} "
        f"turns={result.turns:2} tokens={result.total_tokens:5} "
        f"time={result.duration_s:6.2f}s cost={format_cost(result.cost_usd)} "
        f"tools={tools}"
    )
    if result.error:
        print(f"  error: {result.error}")
    if result.missing_groups:
        print(f"  missing: {result.missing_groups}")


def print_summary(results: list[CaseResult]) -> None:
    """按模式打印平均指标。"""
    print("\n汇总：")
    for mode in ("rag", "search"):
        mode_results = [result for result in results if result.mode == mode]
        if not mode_results:
            continue
        passed = sum(result.status == "pass" for result in mode_results)
        avg_turns = sum(
            result.turns for result in mode_results) / len(mode_results)
        avg_tokens = (
            sum(result.total_tokens for result in mode_results)
            / len(mode_results)
        )
        avg_duration = (
            sum(result.duration_s for result in mode_results)
            / len(mode_results)
        )
        known_costs = [
            result.cost_usd
            for result in mode_results
            if result.cost_usd is not None
        ]
        avg_cost = (
            sum(known_costs) / len(known_costs)
            if known_costs
            else None
        )
        print(
            f"{mode:6}: pass={passed}/{len(mode_results)} "
            f"avg_turns={avg_turns:.2f} avg_tokens={avg_tokens:.0f} "
            f"avg_time={avg_duration:.2f}s avg_cost={format_cost(avg_cost)}"
        )


async def run_experiment(args: argparse.Namespace) -> list[CaseResult]:
    """运行选定模式的全部问题。"""
    workdir = args.workdir.resolve()
    cases = load_cases(args.cases.resolve())
    modes: list[ExperimentMode] = (
        ["rag", "search"] if args.mode == "both" else [args.mode]
    )
    if "rag" in modes:
        index_path = workdir / ".agent-mini" / "rag-index.json"
        if not index_path.is_file():
            raise FileNotFoundError(
                f"RAG 索引不存在，请先生成: {index_path}"
            )
        load_index(index_path)

    settings = AgentSettings()
    # 两组顺序执行时关闭 prompt cache，避免后运行的组因缓存命中而获得
    # 不公平的 token 和费用优势。
    settings.prompt_cache_enabled = False

    results: list[CaseResult] = []
    for mode in modes:
        for case in cases:
            result = await run_case(
                case,
                mode,
                workdir=workdir,
                settings=settings,
                max_turns=args.max_turns,
                max_tokens=args.max_tokens,
                max_cost_usd=args.max_cost_usd,
            )
            results.append(result)
            print_result(result)
    return results


def save_results(path: Path, results: list[CaseResult]) -> None:
    """保存完整实验结果，便于后续人工复盘。"""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [asdict(result) for result in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main() -> None:
    """运行实验并输出对比结果。"""
    args = parse_args()
    results = await run_experiment(args)
    print_summary(results)
    if args.show_answers:
        print("\n模型回答：")
        for result in results:
            print(f"\n[{result.mode}] {result.case_id}\n{result.answer}")
    if args.output:
        save_results(args.output, results)
        print(f"\n完整结果已写入: {args.output.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
