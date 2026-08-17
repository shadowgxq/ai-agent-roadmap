"""发现、运行并汇总 agent-mini Eval Framework v2 cases。"""

from __future__ import annotations
from src.agent.runtime import run_coding_agent
from src.agent.loop import (
    CostLimitExceeded,
    MaxTurnsExceeded,
    message_text,
)
from src.agent.logging_config import configure_logging, get_logger
from src.agent.cost import estimate_cost
from src.agent.config import AgentSettings
from evals.analysis import (
    aggregate_usage,
    classify_failure,
    summarize_buckets,
    summarize_failure_categories,
    usage_metrics,
)

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Literal

import yaml
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

# `python evals/run.py` 把 evals 目录放在 sys.path 首位，显式补入项目根目录，
# 让它和 `python -m evals.run` 使用同一套导入行为。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if __package__:
    from .assertions import (
        AssertionResult,
        evaluate_behavior,
        format_failures,
        snapshot_workspace,
    )
    from .judge import JudgeResult, judge_output
else:
    from assertions import (
        AssertionResult,
        evaluate_behavior,
        format_failures,
        snapshot_workspace,
    )
    from judge import JudgeResult, judge_output


EVALS_ROOT = Path(__file__).resolve().parent
CASES_ROOT = EVALS_ROOT / "cases"
REGRESSION_ROOT = EVALS_ROOT / "regression"
logger = get_logger("evals")

EvalType = Literal["command", "judge", "behavior"]
ToolMode = Literal["all", "rag", "search"]


def parse_args() -> argparse.Namespace:
    """解析 Eval 套件、单 case 和日志参数。"""
    parser = argparse.ArgumentParser(
        description="运行 agent-mini Eval Framework v2 cases。"
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_names",
        help="只运行指定 case；可重复传入。传入后忽略 --suite。",
    )
    parser.add_argument(
        "--suite",
        default="core",
        help="运行包含该 suite 标签的 cases，默认 core；full/all 表示全部。",
    )
    parser.add_argument(
        "--experiment",
        default="baseline",
        help="写入 Langfuse metadata 的实验名称。",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="JSONL 运行日志；默认 logs/agent.jsonl，按运行追加写入。",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=None,
        help="独立评测报告；默认 logs/evals/<experiment>.json。",
    )
    return parser.parse_args()


@dataclass
class EvalResult:
    """记录一个 case 的验证结果、能力标签和 Trace 关联。"""

    case_name: str
    eval_type: EvalType
    status: Literal["pass", "fail", "scored", "error"]
    difficulty: str = "L1"
    capabilities: list[str] | None = None
    turns: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    reason: str = ""
    judge_result: JudgeResult | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    judge_model: str | None = None
    judge_independent: bool | None = None
    trajectory: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)
    usage: dict[str, int | float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """保证日志和汇总始终拿到独立的能力列表。"""
        if self.capabilities is None:
            self.capabilities = []


class EvalCase(BaseModel):
    """一个可执行 Eval case 的统一配置协议。"""

    task: str = Field(min_length=1)
    eval_type: EvalType = "command"
    difficulty: str = Field(default="L1", min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    suite: list[str] = Field(default_factory=lambda: ["core"])
    verify_cmd: str | None = None
    judge_reference_file: str | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    min_clarification_score: int = Field(default=4, ge=1, le=5)
    agent_timeout_s: int = Field(default=180, gt=0)
    timeout_s: int = Field(default=60, gt=0)
    max_cost_usd: float = Field(default=5, gt=0)
    trace_metadata: dict[str, Any] = Field(default_factory=dict)
    trace_tags: list[str] = Field(default_factory=list)
    mcp_config_file: str | None = None
    tool_mode: ToolMode = "all"

    @model_validator(mode="after")
    def validate_verifier(self) -> "EvalCase":
        """确保每种 case 都声明了自己需要的验证输入。"""
        if not self.suite:
            raise ValueError("suite 至少需要包含一个标签")
        if self.eval_type == "command" and not self.verify_cmd:
            raise ValueError("command case 必须配置 verify_cmd")
        if self.eval_type == "judge" and not self.judge_reference_file:
            raise ValueError("judge case 必须配置 judge_reference_file")
        if self.eval_type == "behavior" and not self.expected:
            raise ValueError("behavior case 必须配置 expected")
        if self.expected.get("should_clarify") and not self.judge_reference_file:
            raise ValueError(
                "should_clarify behavior case 必须配置 judge_reference_file"
            )
        if self.mcp_config_file and self.tool_mode != "all":
            raise ValueError("配置 MCP 时 tool_mode 必须为 all")
        return self


def discover_cases(
    cases_root: Path = CASES_ROOT,
    regression_root: Path = REGRESSION_ROOT,
) -> list[Path]:
    """递归发现 Core 和 Regression 下所有包含 case.yaml 的目录。"""
    roots = [cases_root, regression_root]
    case_files: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        case_files.update(root.rglob("case.yaml"))
    return sorted(
        (path.parent for path in case_files),
        key=lambda path: path.name,
    )


def load_case(path: Path) -> EvalCase:
    """读取 YAML 配置，并将其校验为 EvalCase。"""
    with path.open(encoding="utf-8") as file:
        data: Any = yaml.safe_load(file)
    return EvalCase.model_validate(data)


def select_cases(
    case_dirs: list[Path],
    *,
    suite: str,
    case_names: list[str] | None,
) -> list[Path]:
    """按 case 名称或 suite 筛选，并拒绝拼写错误的 case。"""
    case_by_name: dict[str, Path] = {}
    for case_dir in case_dirs:
        case_name = case_dir.name
        if case_name in case_by_name:
            raise ValueError(f"发现重复 case 名称: {case_name}")
        case_by_name[case_name] = case_dir

    if case_names:
        unknown = sorted(set(case_names) - set(case_by_name))
        if unknown:
            raise ValueError("找不到 case: " + ", ".join(unknown))
        return [case_by_name[name] for name in case_names]

    if suite in {"all", "full"}:
        return case_dirs

    selected: list[Path] = []
    for case_dir in case_dirs:
        case = load_case(case_dir / "case.yaml")
        if suite in case.suite:
            selected.append(case_dir)
    return selected


def copy_fixture(case_dir: Path, temp_root: Path) -> Path:
    """把 case 的原始仓库复制到临时目录，并返回工作目录。"""
    source = case_dir / "repo"
    if not source.is_dir():
        raise FileNotFoundError(f"case 缺少 repo fixture: {source}")
    workspace = temp_root / "repo"
    shutil.copytree(source, workspace)
    return workspace


@contextmanager
def temporary_workspace(case_dir: Path) -> Iterator[Path]:
    """创建 fixture 的临时副本，并在使用结束后自动删除。"""
    with tempfile.TemporaryDirectory(
        prefix=f"agent-mini-eval-{case_dir.name}-"
    ) as temp_dir:
        yield copy_fixture(case_dir, Path(temp_dir))


def verify_workspace(
    workspace: Path,
    command: str,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    """在临时工作目录中执行客观验证命令。"""
    environment = os.environ.copy()
    if shutil.which("uv", path=environment.get("PATH")) is None:
        local_uv = Path.home() / ".local" / "bin" / "uv"
        if local_uv.is_file():
            environment["PATH"] = (
                f"{local_uv.parent}{os.pathsep}"
                f"{environment.get('PATH', '')}"
            )
    if os.name != "nt":
        # WSL 继承的 Windows TEMP 路径虽然可能可见，但不适合作为 pytest
        # 捕获文件目录；评测子进程统一使用 Linux 临时目录。
        for temp_variable in ("TMPDIR", "TMP", "TEMP"):
            environment[temp_variable] = "/tmp"
    return subprocess.run(
        command,
        cwd=workspace,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        env=environment,
    )


def build_verification_result(
    *,
    case: EvalCase,
    case_name: str,
    completed: subprocess.CompletedProcess[str],
    duration_s: float,
) -> EvalResult:
    """把验证命令结果转换成统一的 EvalResult。"""
    if completed.returncode == 0:
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type,
            status="pass",
            difficulty=case.difficulty,
            capabilities=case.capabilities,
            duration_s=duration_s,
        )

    output = "\n".join(
        part
        for part in (
            completed.stdout.strip(),
            completed.stderr.strip(),
        )
        if part
    )
    reason = output[-2000:] or f"验证命令退出码: {completed.returncode}"
    return EvalResult(
        case_name=case_name,
        eval_type=case.eval_type,
        status="fail",
        difficulty=case.difficulty,
        capabilities=case.capabilities,
        duration_s=duration_s,
        reason=reason,
    )


def build_case_settings(
    settings: AgentSettings,
    case: EvalCase,
    workspace: Path,
) -> AgentSettings:
    """把 case 内的可选 MCP 配置映射到本次 Agent 运行。"""
    if case.mcp_config_file is None:
        return settings

    mcp_config = (workspace / case.mcp_config_file).resolve()
    if not mcp_config.is_file():
        raise FileNotFoundError(f"case MCP 配置不存在: {mcp_config}")
    return settings.model_copy(
        update={
            "mcp_enabled": True,
            "mcp_config_file": mcp_config,
        }
    )


def read_judge_reference(case_dir: Path, case: EvalCase) -> str:
    """读取与 case.yaml 同级的 Judge 参考事实。"""
    if case.judge_reference_file is None:
        raise ValueError("judge case 缺少 judge_reference_file")
    reference_path = (case_dir / case.judge_reference_file).resolve()
    try:
        reference_path.relative_to(case_dir.resolve())
    except ValueError as exc:
        raise ValueError("judge_reference_file 不能跳出 case 目录") from exc
    if not reference_path.is_file():
        raise FileNotFoundError(f"Judge reference 不存在: {reference_path}")
    return reference_path.read_text(encoding="utf-8")


async def run_case(
    case_dir: Path,
    settings: AgentSettings,
    *,
    experiment: str = "baseline",
) -> EvalResult:
    """运行一个 case，并按 command/judge/behavior 分派验证器。"""
    case_name = case_dir.name
    started_at = perf_counter()
    turns = 0
    cost_usd = 0.0
    trace_id: str | None = None
    trace_url: str | None = None
    judge_model: str | None = None
    judge_independent: bool | None = None
    trajectory: dict[str, Any] = {}
    assertions: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int | float | None] = {}
    case: EvalCase | None = None

    try:
        case = load_case(case_dir / "case.yaml")
        if settings.price_currency.upper() != "USD":
            raise ValueError("Eval 的费用配置要求价格货币使用 USD")
        if (
            settings.input_price_per_million is None
            or settings.output_price_per_million is None
        ):
            raise ValueError("缺少输入或输出单价，无法计算 Eval 费用")

        with temporary_workspace(case_dir) as workspace:
            case_settings = build_case_settings(settings, case, workspace)
            before_snapshot = snapshot_workspace(workspace)
            final_response, stats = await asyncio.wait_for(
                run_coding_agent(
                    task=case.task,
                    workdir=workspace,
                    settings=case_settings,
                    max_cost_usd=case.max_cost_usd,
                    tool_mode=case.tool_mode,
                    trace_metadata={
                        "case_id": case_name,
                        "experiment": experiment,
                        "eval_type": case.eval_type,
                        "difficulty": case.difficulty,
                        "capabilities": case.capabilities,
                        "suite": case.suite,
                        **case.trace_metadata,
                    },
                    trace_tags=[
                        "eval",
                        experiment,
                        case.eval_type,
                        *case.suite,
                        *case.trace_tags,
                    ],
                ),
                timeout=case.agent_timeout_s,
            )
            turns = stats.turns
            trace_id = stats.trace_id
            trace_url = stats.trace_url
            aggregate_stats = stats.aggregate()
            trajectory = aggregate_stats.trajectory_metrics()
            tool_calls = aggregate_stats.tool_calls
            usage = usage_metrics(aggregate_stats)
            after_snapshot = snapshot_workspace(workspace)
            estimated_cost = estimate_cost(stats, case_settings)
            if estimated_cost is None:
                raise ValueError("缺少完整的模型价格配置，无法计算 Eval 费用")
            cost_usd = estimated_cost
            agent_answer = message_text(final_response.choices[0].message)

            if case.eval_type == "command":
                completed = verify_workspace(
                    workspace,
                    case.verify_cmd or "",
                    case.timeout_s,
                )
                result = build_verification_result(
                    case=case,
                    case_name=case_name,
                    completed=completed,
                    duration_s=perf_counter() - started_at,
                )
            elif case.eval_type == "behavior":
                behavior_assertions = evaluate_behavior(
                    tool_calls=tool_calls,
                    expected=case.expected,
                    before=before_snapshot,
                    after=after_snapshot,
                )
                assertions = [
                    assertion.to_dict()
                    for assertion in behavior_assertions
                ]
                deterministic_pass = all(
                    assertion.passed for assertion in behavior_assertions
                )
                result = EvalResult(
                    case_name=case_name,
                    eval_type="behavior",
                    status="pass" if deterministic_pass else "fail",
                    difficulty=case.difficulty,
                    capabilities=case.capabilities,
                    duration_s=perf_counter() - started_at,
                    reason=(
                        ""
                        if deterministic_pass
                        else "行为断言失败: "
                        + format_failures(behavior_assertions)
                    ),
                    assertions=assertions,
                    tool_calls=tool_calls,
                )
            if case.eval_type == "judge" or case.judge_reference_file:
                reference = read_judge_reference(case_dir, case)
                judge_model = case_settings.judge_model or case_settings.model
                judge_independent = (
                    case_settings.judge_model is not None
                    and case_settings.judge_model != case_settings.model
                )
                async with AsyncOpenAI(
                    api_key=case_settings.api_key,
                    base_url=case_settings.base_url,
                    max_retries=0,
                    timeout=case.agent_timeout_s,
                ) as judge_client:
                    try:
                        judge_run = await asyncio.wait_for(
                            judge_output(
                                client=judge_client,
                                settings=case_settings,
                                case_name=case_name,
                                task=case.task,
                                reference=reference,
                                answer=agent_answer,
                                trace_id=trace_id,
                                tool_calls=tool_calls,
                                include_clarification=(
                                    case.expected.get("should_clarify")
                                    is True
                                ),
                            ),
                            timeout=case.agent_timeout_s,
                        )
                    except asyncio.TimeoutError:
                        return EvalResult(
                            case_name=case_name,
                            eval_type=case.eval_type,
                            status="error",
                            difficulty=case.difficulty,
                            capabilities=case.capabilities,
                            turns=turns,
                            duration_s=perf_counter() - started_at,
                            cost_usd=cost_usd,
                            reason=(
                                f"Judge 运行超过 {case.agent_timeout_s} 秒"
                            ),
                            trace_id=trace_id,
                            trace_url=trace_url,
                            judge_model=judge_model,
                            judge_independent=judge_independent,
                            trajectory=trajectory,
                            assertions=assertions,
                            tool_calls=tool_calls,
                            usage=usage,
                        )
                cost_usd += judge_run.cost_usd
                if cost_usd > case.max_cost_usd:
                    return EvalResult(
                        case_name=case_name,
                        eval_type=case.eval_type,
                        status="fail",
                        difficulty=case.difficulty,
                        capabilities=case.capabilities,
                        turns=turns,
                        duration_s=perf_counter() - started_at,
                        cost_usd=cost_usd,
                        reason=(
                            f"Agent + Judge 总费用 ${cost_usd:.6f}"
                            f" 超过 case 预算 ${case.max_cost_usd:.6f}"
                        ),
                        trace_id=trace_id,
                        trace_url=trace_url,
                        judge_model=judge_model,
                        judge_independent=judge_independent,
                        trajectory=trajectory,
                        assertions=assertions,
                        tool_calls=tool_calls,
                        usage=usage,
                    )
                if case.eval_type == "judge":
                    result = EvalResult(
                        case_name=case_name,
                        eval_type="judge",
                        status="scored",
                        difficulty=case.difficulty,
                        capabilities=case.capabilities,
                        duration_s=perf_counter() - started_at,
                        judge_result=judge_run.result,
                    )
                else:
                    result.judge_result = judge_run.result
                    if case.expected.get("should_clarify") is True:
                        score = judge_run.result.clarification_score
                        clarification_pass = (
                            score is not None
                            and score >= case.min_clarification_score
                        )
                        clarification_assertion = AssertionResult(
                            name="should_clarify",
                            passed=clarification_pass,
                            expected=(
                                f"clarification_score >= "
                                f"{case.min_clarification_score}"
                            ),
                            actual=score,
                            detail=judge_run.result.reasoning,
                        ).to_dict()
                        assertions.append(clarification_assertion)
                        result.assertions = assertions
                        if not clarification_pass:
                            result.status = "fail"
                            result.reason = (
                                result.reason + "; "
                                if result.reason
                                else ""
                            ) + (
                                "Judge 澄清断言失败: "
                                f"clarification_score={score}"
                            )

            result.turns = turns
            result.cost_usd = cost_usd
            result.trace_id = trace_id
            result.trace_url = trace_url
            result.judge_model = judge_model
            result.judge_independent = judge_independent
            result.trajectory = trajectory
            result.assertions = assertions
            result.tool_calls = tool_calls
            result.failure_categories = classify_failure(result)
            result.usage = usage
            return result
    except CostLimitExceeded as exc:
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type if case is not None else "command",
            status="fail",
            turns=exc.stats.turns,
            duration_s=perf_counter() - started_at,
            cost_usd=exc.actual_cost_usd,
            reason=str(exc),
            trace_id=exc.stats.trace_id,
            trace_url=exc.stats.trace_url,
            trajectory=exc.stats.aggregate().trajectory_metrics(),
            tool_calls=exc.stats.aggregate().tool_calls,
            usage=usage_metrics(exc.stats),
        )
    except MaxTurnsExceeded as exc:
        estimated_cost = estimate_cost(exc.stats, settings)
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type if case is not None else "command",
            status="error",
            turns=exc.stats.turns,
            duration_s=perf_counter() - started_at,
            cost_usd=estimated_cost or 0.0,
            reason=str(exc),
            trace_id=exc.stats.trace_id,
            trace_url=exc.stats.trace_url,
            trajectory=exc.stats.aggregate().trajectory_metrics(),
            tool_calls=exc.stats.aggregate().tool_calls,
            usage=usage_metrics(exc.stats),
        )
    except asyncio.TimeoutError:
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type if case is not None else "command",
            status="error",
            turns=turns,
            duration_s=perf_counter() - started_at,
            cost_usd=cost_usd,
            reason=f"Agent 运行超过 {case.agent_timeout_s if case else 180} 秒",
            trace_id=trace_id,
            trace_url=trace_url,
            trajectory=trajectory,
            assertions=assertions,
            tool_calls=tool_calls,
            usage=usage,
        )
    except subprocess.TimeoutExpired as exc:
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type if case is not None else "command",
            status="error",
            turns=turns,
            duration_s=perf_counter() - started_at,
            cost_usd=cost_usd,
            reason=f"验证命令超过 {exc.timeout} 秒",
            trace_id=trace_id,
            trace_url=trace_url,
            trajectory=trajectory,
            assertions=assertions,
            tool_calls=tool_calls,
            usage=usage,
        )
    except Exception as exc:
        return EvalResult(
            case_name=case_name,
            eval_type=case.eval_type if case is not None else "command",
            status="error",
            turns=turns,
            duration_s=perf_counter() - started_at,
            cost_usd=cost_usd,
            reason=f"{type(exc).__name__}: {exc}",
            trace_id=trace_id,
            trace_url=trace_url,
            trajectory=trajectory,
            assertions=assertions,
            tool_calls=tool_calls,
            usage=usage,
        )


def log_result(result: EvalResult) -> None:
    """只在终端显示一个 case 的状态、评分和失败原因。"""
    label = result.status.upper()
    failure_categories = result.failure_categories or classify_failure(result)
    summary = (
        f"[{label}] {result.case_name} ({result.eval_type}) | "
        f"turns={result.turns} | "
        f"duration={result.duration_s:.2f}s"
    )
    data: dict[str, Any] = {
        "case": result.case_name,
        "eval_type": result.eval_type,
        "status": result.status,
        "difficulty": result.difficulty,
        "capabilities": result.capabilities,
        "turns": result.turns,
        "duration_s": result.duration_s,
        "reason": result.reason or None,
        "trace_id": result.trace_id,
        "trace_url": result.trace_url,
        "judge_model": result.judge_model,
        "judge_independent": result.judge_independent,
        "trajectory": result.trajectory,
        "assertions": result.assertions,
        "failure_categories": failure_categories,
    }
    if result.judge_result is not None:
        data["judge"] = result.judge_result.model_dump()
        summary += (
            f" | accuracy={result.judge_result.accuracy}"
            f" completeness={result.judge_result.completeness}"
            f" conciseness={result.judge_result.conciseness}"
        )
        if result.judge_result.clarification_score is not None:
            summary += (
                f" clarification={result.judge_result.clarification_score}"
            )
    if result.reason:
        reason_preview = " ".join(result.reason.split())
        if len(reason_preview) > 200:
            reason_preview = (
                reason_preview[:200]
                + f"...[truncated, total={len(reason_preview)} chars]"
            )
        summary += f" | reason={reason_preview}"
    logger.info(summary, extra={"event": "eval.case_completed", "data": data})
    if result.trace_url:
        logger.info(
            "Trace URL: %s",
            result.trace_url,
            extra={
                "event": "eval.trace_url",
                "data": {"case": result.case_name, "url": result.trace_url},
            },
        )
    if result.reason:
        logger.info(
            "原因:\n%s",
            result.reason,
            extra={
                "event": "eval.case_reason",
                "data": {"case": result.case_name, "reason": result.reason},
            },
        )
    if failure_categories:
        logger.info(
            "失败分类: %s",
            ", ".join(failure_categories),
            extra={
                "event": "eval.failure_classified",
                "data": {
                    "case": result.case_name,
                    "categories": failure_categories,
                },
            },
        )


def _average(values: list[float]) -> float | None:
    """返回一组分数的平均值。"""
    return sum(values) / len(values) if values else None


def summarize_trajectory(results: list[EvalResult]) -> dict[str, Any]:
    """汇总每个 case 的轨迹指标，不把它们误当成结果分数。"""
    return {
        "tool_call_count": sum(
            int(result.trajectory.get("tool_call_count", 0))
            for result in results
        ),
        "tool_failure_count": sum(
            int(result.trajectory.get("tool_failure_count", 0))
            for result in results
        ),
        "subagent_used_cases": sum(
            bool(result.trajectory.get("subagent_used", False))
            for result in results
        ),
        "mcp_used_cases": sum(
            bool(result.trajectory.get("mcp_used", False))
            for result in results
        ),
        "verification_command_used_cases": sum(
            bool(result.trajectory.get("verification_command_used", False))
            for result in results
        ),
        "recovered_after_tool_failure_cases": sum(
            bool(
                result.trajectory.get(
                    "recovered_after_tool_failure", False
                )
            )
            for result in results
        ),
    }


def log_summary(results: list[EvalResult]) -> None:
    """只输出评测结果、行为指标和性能摘要。"""
    command_results = [
        result for result in results if result.eval_type == "command"
    ]
    behavior_results = [
        result for result in results if result.eval_type == "behavior"
    ]
    judge_results = [
        result
        for result in results
        if result.judge_result is not None
    ]
    counts = {
        status: sum(result.status == status for result in results)
        for status in ("pass", "fail", "scored", "error")
    }
    turns = sum(result.turns for result in results)
    duration = sum(result.duration_s for result in results)
    cost = sum(result.cost_usd for result in results)
    trajectory = summarize_trajectory(results)
    failure_categories = summarize_failure_categories(results)

    command_pass = sum(result.status == "pass" for result in command_results)
    command_total = len(command_results)
    command_rate = (
        command_pass / command_total * 100 if command_total else None
    )
    judge_averages: dict[str, float | None] = {}
    for dimension in (
        "accuracy",
        "completeness",
        "conciseness",
        "clarification_score",
    ):
        values = [
            getattr(result.judge_result, dimension)
            for result in judge_results
            if getattr(result.judge_result, dimension) is not None
        ]
        if values:
            judge_averages[dimension] = _average(values)

    average_turns = turns / len(results) if results else 0
    average_duration = duration / len(results) if results else 0
    average_cost = cost / len(results) if results else 0
    lines = [
        "Eval Summary",
        "=" * 30,
        f"Cases        {len(results)}",
        f"Passed       {counts['pass']}",
        f"Failed       {counts['fail']}",
        f"Scored       {counts['scored']}",
        f"Errors       {counts['error']}",
    ]
    if command_total:
        lines.append(
            f"Command: {command_pass}/{command_total} PASS"
            f" ({command_rate:.1f}%)"
        )
    if behavior_results:
        behavior_pass = sum(
            result.status == "pass" for result in behavior_results
        )
        lines.append(
            f"Objective: {behavior_pass}/{len(behavior_results)} PASS"
            f" ({behavior_pass / len(behavior_results) * 100:.1f}%)"
        )
    if judge_results:
        lines.append(
            "Judge: "
            + ", ".join(
                f"{dimension}={value:.2f}"
                for dimension, value in judge_averages.items()
                if value is not None
            )
        )
    if failure_categories:
        lines.append(
            "Failures     "
            + ", ".join(
                f"{category}={count}"
                for category, count in sorted(failure_categories.items())
            )
        )
    lines.extend(
        [
            "Behavior",
            f"  Tool failures {trajectory['tool_failure_count']}",
            "  Recovered     "
            f"{trajectory['recovered_after_tool_failure_cases']}",
            "Performance",
            f"  Avg turns     {average_turns:.1f}",
            f"  Avg duration  {average_duration:.1f}s",
            f"Cost           ${cost:.6f} (avg ${average_cost:.6f})",
        ]
    )
    logger.info(
        "\n%s",
        "\n".join(lines),
        extra={
            "event": "eval.completed",
            "data": {
                "counts": counts,
                "command_pass": command_pass,
                "command_total": command_total,
                "command_pass_rate": command_rate,
                "judge_averages": judge_averages,
                "failure_categories": failure_categories,
                "turns": turns,
                "duration_s": duration,
                "cost_usd": cost,
                "trajectory": trajectory,
            },
        },
    )


def write_report(
    path: Path,
    *,
    experiment: str,
    suite: str,
    selected_cases: list[Path],
    results: list[EvalResult],
) -> Path:
    """持久化一次实验的完整结果，避免下一次运行覆盖历史证据。"""
    counts = {
        status: sum(result.status == status for result in results)
        for status in ("pass", "fail", "scored", "error")
    }
    command_results = [
        result for result in results if result.eval_type == "command"
    ]
    behavior_results = [
        result for result in results if result.eval_type == "behavior"
    ]
    judge_results = [
        result
        for result in results
        if result.judge_result is not None
    ]
    trajectory = summarize_trajectory(results)
    buckets = summarize_buckets(results)
    failure_categories = summarize_failure_categories(results)
    usage = aggregate_usage(results)
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 3,
        "experiment": experiment,
        "suite": suite,
        "cases": [path.name for path in selected_cases],
        "summary": {
            "total": len(results),
            "counts": counts,
            "command_pass": sum(
                result.status == "pass" for result in command_results
            ),
            "command_total": len(command_results),
            "behavior_pass": sum(
                result.status == "pass" for result in behavior_results
            ),
            "behavior_total": len(behavior_results),
            "judge_averages": {
                dimension: _average(
                    [
                        getattr(result.judge_result, dimension)
                        for result in judge_results
                        if getattr(result.judge_result, dimension) is not None
                    ]
                )
                for dimension in (
                    "accuracy",
                    "completeness",
                    "conciseness",
                    "clarification_score",
                )
            },
            "buckets": buckets,
            "failure_categories": failure_categories,
            "turns": sum(result.turns for result in results),
            "duration_s": sum(result.duration_s for result in results),
            "cost_usd": sum(result.cost_usd for result in results),
            "avg_cost_usd": (
                sum(result.cost_usd for result in results) / len(results)
                if results
                else 0.0
            ),
            "usage": usage,
            "trajectory": trajectory,
        },
        "results": [
            {
                "case": result.case_name,
                "eval_type": result.eval_type,
                "status": result.status,
                "difficulty": result.difficulty,
                "capabilities": result.capabilities,
                "turns": result.turns,
                "duration_s": result.duration_s,
                "cost_usd": result.cost_usd,
                "reason": result.reason or None,
                "trace_id": result.trace_id,
                "trace_url": result.trace_url,
                "judge_model": result.judge_model,
                "judge_independent": result.judge_independent,
                "trajectory": result.trajectory,
                "assertions": result.assertions,
                "failure_categories": (
                    result.failure_categories or classify_failure(result)
                ),
                "usage": result.usage,
                "judge": (
                    result.judge_result.model_dump()
                    if result.judge_result is not None
                    else None
                ),
            }
            for result in results
        ],
    }
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)
    logger.info(
        "评测报告: %s",
        path,
        extra={
            "event": "eval.report_written",
            "data": {"path": str(path), "experiment": experiment},
        },
    )
    return path


async def main() -> None:
    """顺序运行选中的 cases，避免并发请求干扰结果和日志。"""
    args = parse_args()
    settings = AgentSettings()
    log_file = configure_logging(args.log_file or settings.log_file)
    logger.info(
        "详细日志: %s",
        log_file,
        extra={
            "event": "eval.started",
            "data": {
                "log_file": str(log_file),
                "suite": args.suite,
                "case_names": args.case_names,
                "experiment": args.experiment,
            },
        },
    )

    case_dirs = discover_cases()
    if not case_dirs:
        logger.warning(
            "没有发现 Eval case: %s",
            EVALS_ROOT,
            extra={"event": "eval.no_cases"},
        )
        return

    try:
        selected_cases = select_cases(
            case_dirs,
            suite=args.suite,
            case_names=args.case_names,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if not selected_cases:
        raise SystemExit(f"suite 没有匹配的 case: {args.suite}")

    logger.info(
        "选中 %s 个 cases: %s",
        len(selected_cases),
        ", ".join(path.name for path in selected_cases),
        extra={
            "event": "eval.cases_selected",
            "data": {
                "count": len(selected_cases),
                "cases": [path.name for path in selected_cases],
            },
        },
    )

    results: list[EvalResult] = []
    for case_dir in selected_cases:
        logger.info(
            "[RUN] %s",
            case_dir.name,
            extra={
                "event": "eval.case_started",
                "data": {"case": case_dir.name},
            },
        )
        result = await run_case(
            case_dir,
            settings,
            experiment=args.experiment,
        )
        results.append(result)
        log_result(result)

    log_summary(results)
    safe_experiment = re.sub(r"[^A-Za-z0-9_.-]+", "-", args.experiment)
    safe_experiment = safe_experiment.strip("-") or "baseline"
    report_file = args.report_file or (
        PROJECT_ROOT / "logs" / "evals" / f"{safe_experiment}.json"
    )
    write_report(
        report_file,
        experiment=args.experiment,
        suite=args.suite,
        selected_cases=selected_cases,
        results=results,
    )


if __name__ == "__main__":
    asyncio.run(main())
