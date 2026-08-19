"""Shell 命令的策略层安全护栏。"""

from __future__ import annotations

import re
import shlex
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field


class PolicyAction(StrEnum):
    """Shell 命令的处理动作。"""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class PolicyDecision(BaseModel):
    """一次 Shell 策略判断的可解释结果。"""

    action: PolicyAction
    command: str
    reason: str
    command_name: str | None = None


class Policy(BaseModel):
    """按命令前缀判断 Shell 工具是否可以自动执行。"""

    allowed_commands: set[str] = Field(
        default_factory=lambda: {
            "ls",
            "cat",
            "echo",
            "grep",
            "rg",
            "pytest",
            "python",
            "python3",
            "uv",
            "git status",
            "git diff",
            "git log",
        }
    )
    denied_commands: set[str] = Field(
        default_factory=lambda: {
            "sudo",
            "curl",
            "wget",
            "chmod",
        }
    )
    confirm_commands: set[str] = Field(
        default_factory=lambda: {
            "git push",
            "git clean",
            "git reset --hard",
            "pip install",
            "npm install",
            "rm",
        }
    )

    _compound_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"&&|\|\||[;|]|`|\$\("
    )
    _segment_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"&&|\|\||[;|]"
    )

    def evaluate(self, command: str) -> PolicyDecision:
        """判断命令能否自动执行，不负责真正执行命令。"""
        raw_command = command.strip()
        if not raw_command:
            return PolicyDecision(
                action=PolicyAction.DENY,
                command=command,
                command_name=None,
                reason="命令不能为空",
            )

        try:
            tokens = shlex.split(raw_command)
        except ValueError as exc:
            return PolicyDecision(
                action=PolicyAction.DENY,
                command=command,
                command_name=None,
                reason=f"命令无法安全解析: {exc}",
            )

        if not tokens:
            return PolicyDecision(
                action=PolicyAction.DENY,
                command=command,
                command_name=None,
                reason="命令解析后为空",
            )

        normalized_tokens = self._normalize_tokens(tokens)
        command_name = normalized_tokens[0]

        denied_rule = self._matching_rule(
            normalized_tokens,
            self.denied_commands,
        )
        if denied_rule is None and self._has_compound_syntax(raw_command):
            denied_rule = self._matching_denied_segment(raw_command)
        if denied_rule is not None:
            return PolicyDecision(
                action=PolicyAction.DENY,
                command=command,
                command_name=command_name,
                reason=f"命中禁止命令规则: {denied_rule}",
            )

        if self._has_compound_syntax(raw_command):
            return PolicyDecision(
                action=PolicyAction.CONFIRM,
                command=command,
                command_name=command_name,
                reason="检测到复合 Shell 结构，不能自动执行",
            )

        confirm_rule = self._matching_rule(
            normalized_tokens,
            self.confirm_commands,
        )
        if confirm_rule is not None:
            return PolicyDecision(
                action=PolicyAction.CONFIRM,
                command=command,
                command_name=command_name,
                reason=f"命中需确认命令规则: {confirm_rule}",
            )

        allowed_rule = self._matching_rule(
            normalized_tokens,
            self.allowed_commands,
        )
        if allowed_rule is not None:
            return PolicyDecision(
                action=PolicyAction.ALLOW,
                command=command,
                command_name=command_name,
                reason=f"命中允许命令规则: {allowed_rule}",
            )

        return PolicyDecision(
            action=PolicyAction.CONFIRM,
            command=command,
            command_name=command_name,
            reason="未知命令默认不能自动执行",
        )

    @classmethod
    def _normalize_tokens(cls, tokens: list[str]) -> list[str]:
        """统一可执行文件名，保留后续参数用于多词规则匹配。"""
        normalized = list(tokens)
        normalized[0] = Path(normalized[0]).name
        return normalized

    @classmethod
    def _has_compound_syntax(cls, command: str) -> bool:
        """判断命令是否包含需要人工确认的 Shell 结构。"""
        return cls._compound_pattern.search(command) is not None

    def _matching_denied_segment(self, command: str) -> str | None:
        """在复合命令的各段中优先识别明确的禁止命令。"""
        for segment in self._segment_pattern.split(command):
            try:
                tokens = self._normalize_tokens(shlex.split(segment))
            except ValueError:
                continue
            if not tokens:
                continue
            matched = self._matching_rule(tokens, self.denied_commands)
            if matched is not None:
                return matched
        return None

    @staticmethod
    def _matching_rule(
        tokens: list[str],
        rules: set[str],
    ) -> str | None:
        """匹配最长的命令前缀，避免只把 ``git`` 当成完整规则。"""
        matched_rule: str | None = None
        matched_length = 0
        for rule in rules:
            try:
                rule_tokens = shlex.split(rule)
            except ValueError:
                continue
            if not rule_tokens:
                continue
            rule_tokens[0] = Path(rule_tokens[0]).name
            if tokens[: len(rule_tokens)] != rule_tokens:
                continue
            if len(rule_tokens) > matched_length:
                matched_rule = rule
                matched_length = len(rule_tokens)
        return matched_rule


__all__ = ["Policy", "PolicyAction", "PolicyDecision"]
