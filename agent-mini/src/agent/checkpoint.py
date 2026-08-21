"""持久化 Agent 运行状态，并支持从完整轮次断点恢复。"""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .loop import RunStats


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_DIR = PROJECT_ROOT / ".agent-mini" / "runs"
CheckpointStatus = Literal["running", "completed", "failed", "interrupted"]


class RunStatsSnapshot(BaseModel):
    """可 JSON 序列化的模型用量快照，保留 SubAgent 递归统计。"""

    turns: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    router_calls: int = Field(default=0, ge=0)
    router_input_tokens: int = Field(default=0, ge=0)
    router_output_tokens: int = Field(default=0, ge=0)
    router_cache_read_input_tokens: int = Field(default=0, ge=0)
    router_cache_creation_input_tokens: int = Field(default=0, ge=0)
    router_model: str | None = None
    route: str | None = None
    router_fallback: bool = False
    selected_model: str | None = None
    compact_calls: int = Field(default=0, ge=0)
    compact_input_tokens: int = Field(default=0, ge=0)
    compact_output_tokens: int = Field(default=0, ge=0)
    compact_cache_read_input_tokens: int = Field(default=0, ge=0)
    compact_cache_creation_input_tokens: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    mcp_tool_call_count: int = Field(default=0, ge=0)
    subagent_tool_call_count: int = Field(default=0, ge=0)
    verification_command_count: int = Field(default=0, ge=0)
    tool_failure_count: int = Field(default=0, ge=0)
    recovered_after_tool_failure: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    subagent_runs: list["RunStatsSnapshot"] = Field(default_factory=list)

    @classmethod
    def from_stats(cls, stats: RunStats) -> "RunStatsSnapshot":
        """递归复制运行统计，避免 checkpoint 持有可变运行对象。"""
        return cls(
            turns=stats.turns,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            cache_read_input_tokens=stats.cache_read_input_tokens,
            cache_creation_input_tokens=stats.cache_creation_input_tokens,
            router_calls=stats.router_calls,
            router_input_tokens=stats.router_input_tokens,
            router_output_tokens=stats.router_output_tokens,
            router_cache_read_input_tokens=stats.router_cache_read_input_tokens,
            router_cache_creation_input_tokens=(
                stats.router_cache_creation_input_tokens
            ),
            router_model=stats.router_model,
            route=stats.route,
            router_fallback=stats.router_fallback,
            selected_model=stats.selected_model,
            compact_calls=stats.compact_calls,
            compact_input_tokens=stats.compact_input_tokens,
            compact_output_tokens=stats.compact_output_tokens,
            compact_cache_read_input_tokens=(
                stats.compact_cache_read_input_tokens
            ),
            compact_cache_creation_input_tokens=(
                stats.compact_cache_creation_input_tokens
            ),
            tool_call_count=stats.tool_call_count,
            mcp_tool_call_count=stats.mcp_tool_call_count,
            subagent_tool_call_count=stats.subagent_tool_call_count,
            verification_command_count=stats.verification_command_count,
            tool_failure_count=stats.tool_failure_count,
            recovered_after_tool_failure=(
                stats.recovered_after_tool_failure
            ),
            tool_calls=[dict(call) for call in stats.tool_calls],
            subagent_runs=[cls.from_stats(child)
                           for child in stats.subagent_runs],
        )

    def to_stats(self) -> RunStats:
        """恢复 Agent Loop 使用的 RunStats。"""
        return RunStats(
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            router_calls=self.router_calls,
            router_input_tokens=self.router_input_tokens,
            router_output_tokens=self.router_output_tokens,
            router_cache_read_input_tokens=self.router_cache_read_input_tokens,
            router_cache_creation_input_tokens=(
                self.router_cache_creation_input_tokens
            ),
            router_model=self.router_model,
            route=self.route,
            router_fallback=self.router_fallback,
            selected_model=self.selected_model,
            compact_calls=self.compact_calls,
            compact_input_tokens=self.compact_input_tokens,
            compact_output_tokens=self.compact_output_tokens,
            compact_cache_read_input_tokens=(
                self.compact_cache_read_input_tokens
            ),
            compact_cache_creation_input_tokens=(
                self.compact_cache_creation_input_tokens
            ),
            tool_call_count=self.tool_call_count,
            mcp_tool_call_count=self.mcp_tool_call_count,
            subagent_tool_call_count=self.subagent_tool_call_count,
            verification_command_count=self.verification_command_count,
            tool_failure_count=self.tool_failure_count,
            recovered_after_tool_failure=(
                self.recovered_after_tool_failure
            ),
            tool_calls=[dict(call) for call in self.tool_calls],
            subagent_runs=[child.to_stats() for child in self.subagent_runs],
        )


class Checkpoint(BaseModel):
    """一次 Coding Agent 运行恢复所需的完整状态。"""

    run_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    message_id: str | None = Field(default=None, min_length=1)
    task: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    turn: int = Field(default=0, ge=0)
    stats: RunStatsSnapshot = Field(default_factory=RunStatsSnapshot)
    total_cost_usd: float | None = Field(default=None, ge=0)
    cost: dict[str, Any] = Field(default_factory=dict)
    workdir: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_turns: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    context_window_tokens: int = Field(default=128_000, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    enable_subagent: bool = True
    router_enabled: bool = False
    prompt_cache_enabled: bool = True
    status: CheckpointStatus = "running"
    start_sha: str | None = None

    @field_validator("task", "workdir", "model")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """拒绝无法用于恢复的空白核心字段。"""
        value = value.strip()
        if not value:
            raise ValueError("checkpoint 核心文本字段不能为空")
        return value


def checkpoint_path(run_id: str, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    """返回 run_id 对应的 checkpoint 文件，并拒绝路径穿越。"""
    if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in run_id):
        raise ValueError("run_id 只能包含字母、数字、下划线和连字符")
    return runs_dir / run_id / "checkpoint.json"


def save_checkpoint(
    checkpoint: Checkpoint,
    *,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> Path:
    """先完整写入临时文件，再原子替换正式 checkpoint。"""
    path = checkpoint_path(checkpoint.run_id, runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    payload = checkpoint.model_dump_json(indent=2)

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return path


def load_checkpoint(
    run_id: str,
    *,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> Checkpoint:
    """读取并验证 checkpoint；损坏或缺字段时由 Pydantic 明确报错。"""
    path = checkpoint_path(run_id, runs_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint 不存在: {path}")
    return Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
