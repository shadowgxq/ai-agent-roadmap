"""Command-line entry point for the W16 Session 1 baseline."""

import argparse
import json
from pathlib import Path

from .contracts import TaskCase, TaskSpec
from .planning import (
    DeterministicPlanner,
    LLMPlanner,
    OpenAICompatibleChatModel,
    Planner,
    PlannerModelError,
    PlannerOutputError,
    PlanningRequest,
    compare_strategies,
)
from .runtime import ReactiveBaseline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="advanced-coding-agent",
        description="W16-W18 advanced coding-agent experiments.",
    )
    parser.add_argument(
        "objective",
        nargs="?",
        help="实验任务目标。",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd(),
        help="Agent 允许操作的仓库目录。",
    )
    parser.add_argument(
        "--case-file",
        type=Path,
        help="按 JSON 固定 case 批量运行当前模式。",
    )
    parser.add_argument(
        "--mode",
        choices=("reactive", "planning", "compare"),
        default="reactive",
        help="选择 Reactive、structured planning 或策略对照。",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Planner 约束，可重复传入。",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        help="Planner 可用工具，可重复传入。",
    )
    parser.add_argument(
        "--planner-backend",
        choices=("llm", "deterministic"),
        default=None,
        help="Planning 模式的 Planner；默认使用 LLM，deterministic 仅用于基线。",
    )
    return parser


def _load_case_texts(
    item: dict[str, object],
    field_name: str,
    index: int,
) -> tuple[str, ...]:
    values = item.get(field_name, [])
    if not isinstance(values, list):
        raise ValueError(f"case[{index}].{field_name} 必须是字符串数组。")
    if any(not isinstance(value, str) for value in values):
        raise ValueError(f"case[{index}].{field_name} 必须只包含字符串。")
    return tuple(value.strip() for value in values if value.strip())


def load_cases(path: Path) -> tuple[TaskCase, ...]:
    """Load and validate the small deterministic Session 1 fixture format."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 case 文件 {path}: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise ValueError("case 文件必须是非空 JSON 数组。")

    cases: list[TaskCase] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"case[{index}] 必须是 JSON 对象。")
        try:
            cases.append(
                TaskCase(
                    case_id=str(item["id"]),
                    objective=str(item["objective"]),
                    expected_complexity=item["expected_complexity"],
                    planning_recommended=item["planning_recommended"],
                    constraints=_load_case_texts(item, "constraints", index),
                    available_tools=_load_case_texts(item, "available_tools", index),
                    scenario=item.get("scenario", "normal"),  # type: ignore[arg-type]
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"case[{index}] 格式错误：{exc}") from exc
    return tuple(cases)


def _build_planner(backend: str) -> Planner:
    if backend == "deterministic":
        return DeterministicPlanner()
    return LLMPlanner(OpenAICompatibleChatModel.from_env())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.objective is not None and args.case_file is not None:
        parser.error("objective 与 --case-file 不能同时使用。")
    if args.objective is None and args.case_file is None:
        parser.print_help()
        return 0

    if args.mode == "compare":
        if args.case_file is None:
            parser.error("compare 模式必须提供 --case-file。")
        if args.constraint or args.tool:
            parser.error("compare 模式的约束和工具必须写在 JSON case 中。")
        try:
            cases = load_cases(args.case_file)
        except ValueError as exc:
            parser.error(str(exc))
        result = compare_strategies(cases)
        exit_code = 0 if all(run.success for run in result.runs) else 1
    elif args.mode == "planning":
        try:
            planner = _build_planner(args.planner_backend or "llm")
        except PlannerModelError as exc:
            parser.error(str(exc))
        if args.case_file is not None:
            if args.constraint or args.tool:
                parser.error(
                    "批量 planning case 的 constraints 和 available_tools 必须写在 JSON 中。"
                )
            try:
                cases = load_cases(args.case_file)
            except ValueError as exc:
                parser.error(str(exc))
            try:
                result = planner.plan_cases(cases)
            except (PlannerModelError, PlannerOutputError) as exc:
                parser.error(str(exc))
            exit_code = 0 if all(
                case_result.matches_expectation
                for case_result in result.case_results
            ) else 1
        else:
            try:
                result = planner.plan(
                    PlanningRequest(
                        goal=args.objective,
                        constraints=tuple(args.constraint),
                        available_tools=tuple(args.tool),
                    )
                )
            except (PlannerModelError, PlannerOutputError) as exc:
                parser.error(str(exc))
            exit_code = 0
    else:
        baseline = ReactiveBaseline()
        if args.case_file is not None:
            try:
                cases = load_cases(args.case_file)
            except ValueError as exc:
                parser.error(str(exc))
            result = baseline.run_cases(cases, workdir=args.workdir)
            exit_code = 0 if all(
                case_run.result.status == "completed"
                for case_run in result.case_runs
            ) else 1
        else:
            task = TaskSpec(objective=args.objective, workdir=args.workdir)
            result = baseline.run(task)
            exit_code = 0 if result.status == "completed" else 1

    print(
        json.dumps(
            result.as_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code
