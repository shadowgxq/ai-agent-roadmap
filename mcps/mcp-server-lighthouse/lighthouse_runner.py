"""运行 Lighthouse 并把原始报告压缩成 MCP 可返回的摘要。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field


DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_ERROR_OUTPUT_CHARS = 1200
METRIC_AUDIT_IDS = (
    "first-contentful-paint",
    "largest-contentful-paint",
    "total-blocking-time",
    "cumulative-layout-shift",
    "speed-index",
)


# MCP host 的工作目录不一定是项目目录，因此显式加载当前文件旁的 .env。
# override=False 保证真正的 Shell 环境变量优先于项目默认值。
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)


class AuditIssue(BaseModel):
    """一个需要用户关注的 Lighthouse audit。"""

    id: str
    title: str
    score: float | None = Field(default=None, ge=0, le=1)
    display_value: str | None = None
    recommendation: str


class LighthouseReport(BaseModel):
    """面向模型的精简 Lighthouse 报告。"""

    requested_url: str
    final_url: str
    lighthouse_version: str
    scores: dict[str, int]
    metrics: dict[str, str]
    issues: list[AuditIssue]


class LighthouseError(RuntimeError):
    """Lighthouse 执行或报告解析失败。"""


def validate_url(url: str) -> str:
    """只允许 Lighthouse 能够访问的 HTTP(S) URL。"""

    normalized = url.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise LighthouseError("URL 必须是带主机名的 http:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise LighthouseError("URL 不能包含用户名或密码")
    return normalized


def _to_windows_path(path: Path) -> str:
    """把 WSL 路径转换成 Windows Node 可以读取的路径。"""

    try:
        converted = subprocess.run(
            ["wslpath", "-w", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu-22.04")
        windows_tail = path.as_posix().replace("/", "\\")
        converted = f"\\\\wsl.localhost\\{distro}{windows_tail}"
    if not converted:
        raise LighthouseError(f"无法把 Lighthouse 路径转换为 Windows 路径：{path}")
    return converted


def _lighthouse_command() -> tuple[str, list[str]]:
    """返回 Lighthouse 命令，优先直接调用项目本地 CLI。"""

    configured = os.environ.get("LIGHTHOUSE_BIN", "").strip()
    if configured:
        return configured, []

    project_root = Path(__file__).resolve().parent
    cli_path = project_root / "node_modules" / "lighthouse" / "cli" / "index.js"
    node = shutil.which("node") or shutil.which("node.exe")
    if node and cli_path.is_file():
        cli_argument = cli_path
        # WSL 中经常只有 Windows Node。直接启动 node.exe 可以绕过
        # npx.cmd 对 UNC 当前目录的限制，但脚本参数必须使用 Windows 路径。
        if os.name != "nt" and node.lower().endswith(".exe"):
            cli_argument = _to_windows_path(cli_path)
        return node, [str(cli_argument)]

    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if npx:
        return npx, ["--no-install", "lighthouse"]
    raise LighthouseError(
        "找不到 Node.js。请安装 Node.js 22+，或设置 LIGHTHOUSE_BIN 指向 Lighthouse CLI"
    )


def _shorten(value: str, limit: int = MAX_ERROR_OUTPUT_CHARS) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def _chrome_flags() -> str:
    """构造无界面 Chrome 参数，并处理 WSL/root 下的沙箱限制。"""

    flags = ["--headless=new", "--disable-dev-shm-usage"]
    no_sandbox = os.environ.get("LIGHTHOUSE_NO_SANDBOX", "").lower()
    running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
    running_in_wsl = bool(
        os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")
    )
    using_windows_node_from_wsl = (
        os.name != "nt"
        and shutil.which("node") is None
        and shutil.which("node.exe") is not None
    )
    if (
        no_sandbox in {"1", "true", "yes"}
        or running_as_root
        or running_in_wsl
        or using_windows_node_from_wsl
    ):
        flags.append("--no-sandbox")
    return " ".join(flags)


def _child_environment(executable: str) -> dict[str, str]:
    """为 Lighthouse 子进程选择与 Node 同平台的 Chrome。"""

    environment = os.environ.copy()
    is_windows_node = executable.lower().endswith((".exe", ".cmd"))
    configured = environment.get("CHROME_PATH", "").strip()

    # CHROME_PATH 必须与 Node 同平台；即使用户之前 export 过跨平台配置，
    # 也要清掉它，后面再按当前 Node 平台自动探测。
    configured_is_windows = (
        configured.lower().endswith((".exe", ".cmd"))
        or "/mnt/c/" in configured.lower()
        or bool(re.match(r"^[a-z]:[\\/]", configured.lower()))
        or configured.startswith("\\\\")
    )
    if configured and configured_is_windows == is_windows_node:
        return environment
    environment.pop("CHROME_PATH", None)

    if is_windows_node:
        candidates = (
            Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        )
    else:
        candidates = tuple(
            Path(found)
            for name in ("chromium", "chromium-browser", "google-chrome")
            if (found := shutil.which(name))
        )

    for candidate in candidates:
        if candidate.is_file() or candidate.exists():
            environment["CHROME_PATH"] = str(candidate)
            break
    return environment


async def run_lighthouse(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """通过本地 Lighthouse CLI 生成原始 JSON 报告。"""

    normalized_url = validate_url(url)
    if timeout_seconds <= 0:
        raise LighthouseError("timeout_seconds 必须大于 0")

    executable, prefix = _lighthouse_command()
    child_environment = _child_environment(executable)
    arguments = [
        *prefix,
        normalized_url,
        "--output=json",
        "--output-path=stdout",
        "--quiet",
        "--no-enable-error-reporting",
        "--only-categories=performance,accessibility,best-practices,seo",
        f"--chrome-flags={_chrome_flags()}",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_environment,
        )
    except FileNotFoundError as exc:
        raise LighthouseError(
            f"找不到 Lighthouse 执行命令“{executable}”，请先安装 Node.js 和 Lighthouse"
        ) from exc
    except OSError as exc:
        raise LighthouseError(f"启动 Lighthouse 失败：{exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise LighthouseError(
            f"Lighthouse 执行超过 {timeout_seconds:g} 秒，已终止本次审计"
        ) from exc

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        detail = _shorten(stderr_text) or f"进程退出码：{process.returncode}"
        if "Unable to connect to Chrome" in stderr_text:
            detail += (
                "；Chrome 启动失败，当前配置："
                f" node={executable}"
                f"，CHROME_PATH={child_environment.get('CHROME_PATH', '自动探测')}"
            )
        raise LighthouseError(f"Lighthouse 执行失败：{detail}")

    try:
        return json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise LighthouseError(
            "Lighthouse 没有返回合法 JSON 报告"
            + (f"：{_shorten(stderr_text)}" if stderr_text else "")
        ) from exc


def _percentage(score: Any) -> int | None:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return round(max(0.0, min(1.0, float(score))) * 100)


def _display_value(audit: Mapping[str, Any]) -> str | None:
    display = audit.get("displayValue")
    if display is not None:
        return str(display)

    numeric_value = audit.get("numericValue")
    if isinstance(numeric_value, (int, float)) and not isinstance(numeric_value, bool):
        unit = str(audit.get("numericUnit") or "").strip()
        return f"{numeric_value:g} {unit}".strip()
    return None


def _issue_recommendation(audit: Mapping[str, Any]) -> str:
    description = audit.get("description") or audit.get(
        "title") or "查看该 audit 的详细报告"
    return _shorten(str(description), 300)


def _validate_max_issues(max_issues: int) -> int:
    if isinstance(max_issues, bool) or not isinstance(max_issues, int):
        raise LighthouseError("max_issues 必须是整数")
    if not 1 <= max_issues <= 10:
        raise LighthouseError("max_issues 必须在 1 到 10 之间")
    return max_issues


def summarize_report(
    raw_report: Mapping[str, Any],
    *,
    requested_url: str,
    max_issues: int = 8,
) -> LighthouseReport:
    """从 Lighthouse 原始报告提取分数、指标和有限数量的问题。"""

    max_issues = _validate_max_issues(max_issues)
    categories = raw_report.get("categories")
    audits = raw_report.get("audits")
    if not isinstance(categories, Mapping) or not isinstance(audits, Mapping):
        raise LighthouseError("Lighthouse 报告缺少 categories 或 audits 字段")

    scores: dict[str, int] = {}
    for category_name, category in categories.items():
        if not isinstance(category, Mapping):
            continue
        score = _percentage(category.get("score"))
        if score is not None:
            scores[str(category_name)] = score

    metrics: dict[str, str] = {}
    for audit_id in METRIC_AUDIT_IDS:
        audit = audits.get(audit_id)
        if not isinstance(audit, Mapping):
            continue
        display = _display_value(audit)
        if display:
            metrics[audit_id] = display

    issues: list[AuditIssue] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, Mapping):
            continue
        score = audit.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        if float(score) >= 1:
            continue
        issues.append(
            AuditIssue(
                id=str(audit_id),
                title=str(audit.get("title") or audit_id),
                score=float(score),
                display_value=_display_value(audit),
                recommendation=_issue_recommendation(audit),
            )
        )

    issues.sort(key=lambda issue: (
        issue.score is None, issue.score or 0, issue.title))
    final_url = raw_report.get(
        "finalDisplayedUrl") or raw_report.get("finalUrl")
    return LighthouseReport(
        requested_url=requested_url,
        final_url=str(final_url or requested_url),
        lighthouse_version=str(raw_report.get(
            "lighthouseVersion") or "unknown"),
        scores=scores,
        metrics=metrics,
        issues=issues[:max_issues],
    )
