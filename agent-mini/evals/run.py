"""发现并运行 eval cases，输出单项结果与批量汇总。"""

import asyncio
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from src.agent.config import AgentSettings
from src.agent.cost import estimate_cost
from src.agent.loop import CostLimitExceeded, MaxTurnsExceeded
from src.agent.runtime import run_coding_agent


CASES_ROOT = Path(__file__).resolve().parent / "cases"


@dataclass
class EvalResult:
    """记录一个 eval case 的最终执行结果。"""

    case_name: str
    status: Literal["pass", "fail", "error"]
    turns: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    reason: str = ""


class EvalCase(BaseModel):
    """一个可执行 eval case 的配置。"""

    task: str
    verify_cmd: str
    timeout_s: int = Field(default=60, gt=0)
    max_cost_usd: float = Field(default=5, gt=0)


def discover_cases(cases_root: Path) -> list[Path]:
    """发现包含 case.yaml 的一级子目录，并按名称排序。"""
    if not cases_root.is_dir():
        raise FileNotFoundError(f"Eval cases 目录不存在: {cases_root}")

    return sorted(
        path
        for path in cases_root.iterdir()
        if path.is_dir() and (path / "case.yaml").is_file()
    )


def load_case(path: Path) -> EvalCase:
    """读取 YAML 配置，并将其校验为 EvalCase。"""
    with path.open(encoding="utf-8") as file:
        data: Any = yaml.safe_load(file)

    return EvalCase.model_validate(data)


def copy_fixture(case_dir: Path, temp_root: Path) -> Path:
    """把 case 的原始仓库复制到临时目录，并返回工作目录。"""
    source = case_dir / "repo"
    workspace = temp_root / "repo"

    shutil.copytree(source, workspace)

    return workspace


@contextmanager
def temporary_workspace(case_dir: Path) -> Iterator[Path]:
    """创建 fixture 的临时副本，并在使用结束后自动删除。"""
    with tempfile.TemporaryDirectory(
        prefix=f"agent-mini-eval-{case_dir.name}-"
    ) as temp_dir:
        temp_root = Path(temp_dir)
        workspace = copy_fixture(case_dir, temp_root)
        yield workspace


def verify_workspace(
    workspace: Path,
    command: str,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    """在临时工作目录中执行客观验证命令。"""
    return subprocess.run(
        command,
        cwd=workspace,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def build_verification_result(
    case_name: str,
    completed: subprocess.CompletedProcess[str],
    duration_s: float,
) -> EvalResult:
    """把验证命令结果转换成统一的 eval 结果。"""
    if completed.returncode == 0:
        return EvalResult(
            case_name=case_name,
            status="pass",
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
        status="fail",
        duration_s=duration_s,
        reason=reason,
    )


async def run_case(
    case_dir: Path,
    settings: AgentSettings,
) -> EvalResult:
    """运行一个 eval case，并返回客观验证结果。"""
    case_name = case_dir.name
    started_at = perf_counter()
    turns = 0
    cost_usd = 0.0

    try:
        case = load_case(case_dir / "case.yaml")
        if settings.price_currency.upper() != "USD":
            raise ValueError(
                "Eval 的 max_cost_usd 要求价格配置使用 USD"
            )
        if (
            settings.input_price_per_million is None
            or settings.output_price_per_million is None
        ):
            raise ValueError(
                "缺少输入或输出单价，无法计算 Eval 费用"
            )

        with temporary_workspace(case_dir) as workspace:
            _, stats = await run_coding_agent(
                task=case.task,
                workdir=workspace,
                settings=settings,
                max_cost_usd=case.max_cost_usd,
            )
            turns = stats.turns
            estimated_cost = estimate_cost(stats, settings)
            if estimated_cost is None:
                raise ValueError(
                    "缺少完整的模型价格配置，无法计算 Eval 费用"
                )
            cost_usd = estimated_cost

            completed = verify_workspace(
                workspace,
                case.verify_cmd,
                case.timeout_s,
            )
    except CostLimitExceeded as exc:
        return EvalResult(
            case_name=case_name,
            status="fail",
            turns=exc.stats.turns,
            duration_s=perf_counter() - started_at,
            cost_usd=exc.actual_cost_usd,
            reason=str(exc),
        )
    except MaxTurnsExceeded as exc:
        estimated_cost = estimate_cost(exc.stats, settings)
        return EvalResult(
            case_name=case_name,
            status="error",
            turns=exc.stats.turns,
            duration_s=perf_counter() - started_at,
            cost_usd=estimated_cost or 0.0,
            reason=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        return EvalResult(
            case_name=case_name,
            status="error",
            turns=turns,
            duration_s=perf_counter() - started_at,
            cost_usd=cost_usd,
            reason=f"验证命令超过 {exc.timeout} 秒",
        )
    except Exception as exc:
        return EvalResult(
            case_name=case_name,
            status="error",
            turns=turns,
            duration_s=perf_counter() - started_at,
            cost_usd=cost_usd,
            reason=f"{type(exc).__name__}: {exc}",
        )

    result = build_verification_result(
        case_name=case_name,
        completed=completed,
        duration_s=perf_counter() - started_at,
    )
    result.turns = turns
    result.cost_usd = cost_usd

    return result


def print_result(result: EvalResult) -> None:
    """打印一个 case 的状态、消耗和失败原因。"""
    label = result.status.upper()
    print(
        f"[{label}] {result.case_name} | "
        f"turns={result.turns} | "
        f"duration={result.duration_s:.2f}s | "
        f"cost=${result.cost_usd:.6f}"
    )
    if result.reason:
        print(f"原因:\n{result.reason}")


def print_summary(results: list[EvalResult]) -> None:
    """汇总整批 Eval 的状态、总轮数、总耗时和总费用。"""
    counts = {
        status: sum(result.status == status for result in results)
        for status in ("pass", "fail", "error")
    }
    print("\n===== Eval 汇总 =====")
    print(
        f"{counts['pass']} passed, "
        f"{counts['fail']} failed, "
        f"{counts['error']} errors"
    )
    print(f"总轮数: {sum(result.turns for result in results)}")
    print(f"总耗时: {sum(result.duration_s for result in results):.2f}s")
    print(f"总费用: ${sum(result.cost_usd for result in results):.6f}")


async def main() -> None:
    """顺序运行全部 cases，避免并发请求干扰结果和日志。"""
    case_dirs = discover_cases(CASES_ROOT)
    if not case_dirs:
        print(f"没有发现 Eval case: {CASES_ROOT}")
        return

    settings = AgentSettings()
    results: list[EvalResult] = []

    for case_dir in case_dirs:
        print(f"\n[RUN] {case_dir.name}")
        result = await run_case(case_dir, settings)
        results.append(result)
        print_result(result)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
