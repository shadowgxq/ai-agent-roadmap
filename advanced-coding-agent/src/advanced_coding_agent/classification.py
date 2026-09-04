"""Transparent task classification for the W16 Session 1 baseline."""

import re
from dataclasses import dataclass
from typing import Literal


TaskComplexity = Literal["simple", "complex"]

# Session 1 的候选门槛：预计至少需要两个有依赖的动作，或需要修改后验证、
# 根因调查等中间状态时，建议进入 Planning。后续用 eval 数据校准，而不是把
# 这个启发式规则当成最终的 Planner。
PLANNING_THRESHOLD = (
    "预计至少两个有依赖动作，或包含根因调查、代码修改和后续验证"
)

_COMPLEX_SIGNALS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("修复", "bug", "fix", "debug"), "需要定位或修复问题"),
    (
        ("实现", "新增", "修改", "重构", "implement", "refactor"),
        "可能涉及代码变更",
    ),
    (("运行测试", "测试", "test"), "包含验证步骤"),
    (("定位", "排查", "调查", "diagnose", "trace"), "需要调查根因"),
    (
        ("多文件", "多个步骤", "multi-step", "multiple files"),
        "可能包含多个相关步骤",
    ),
)


@dataclass(frozen=True)
class TaskClassification:
    """A classification decision without creating or executing a plan."""

    complexity: TaskComplexity
    planning_recommended: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "complexity": self.complexity,
            "planning_recommended": self.planning_recommended,
            "reasons": list(self.reasons),
            "planning_threshold": PLANNING_THRESHOLD,
        }


def classify_task(objective: str) -> TaskClassification:
    """Classify a task using visible, deterministic Session 1 signals."""

    normalized = objective.strip().casefold()
    reasons: list[str] = []
    for markers, reason in _COMPLEX_SIGNALS:
        if any(_contains_marker(normalized, marker) for marker in markers):
            reasons.append(reason)

    if reasons:
        return TaskClassification(
            complexity="complex",
            planning_recommended=True,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    return TaskClassification(
        complexity="simple",
        planning_recommended=False,
        reasons=("目标主要是一次只读或解释动作",),
    )


def _contains_marker(text: str, marker: str) -> bool:
    """Match English signals as words while keeping Chinese substring matching."""

    if marker.isascii():
        pattern = rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])"
        return re.search(pattern, text) is not None
    return marker in text
