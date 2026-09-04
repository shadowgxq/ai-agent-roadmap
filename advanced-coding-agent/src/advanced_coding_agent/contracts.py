"""Small contracts shared by the W16 experiment stages."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .classification import TaskClassification, TaskComplexity


ToolStatus = Literal["succeeded", "failed"]
RunStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class TaskSpec:
    """User objective and the repository boundary for one experiment run."""

    objective: str
    workdir: Path
    task_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        objective = self.objective.strip()
        if not objective:
            raise ValueError("objective 不能为空。")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "workdir", Path(self.workdir).resolve())


@dataclass(frozen=True)
class TaskCase:
    """Fixed Session 1 case with an expected classification decision."""

    case_id: str
    objective: str
    expected_complexity: TaskComplexity
    planning_recommended: bool

    def __post_init__(self) -> None:
        case_id = self.case_id.strip()
        objective = self.objective.strip()
        if not case_id:
            raise ValueError("case_id 不能为空。")
        if not objective:
            raise ValueError("objective 不能为空。")
        if self.expected_complexity not in ("simple", "complex"):
            raise ValueError("expected_complexity 必须是 simple 或 complex。")
        if not isinstance(self.planning_recommended, bool):
            raise ValueError("planning_recommended 必须是布尔值。")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "objective", objective)

    def matches(self, classification: TaskClassification) -> bool:
        """Return whether the deterministic classifier matches the fixture."""

        return (
            classification.complexity == self.expected_complexity
            and classification.planning_recommended == self.planning_recommended
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.case_id,
            "objective": self.objective,
            "expected_complexity": self.expected_complexity,
            "planning_recommended": self.planning_recommended,
        }


@dataclass(frozen=True)
class ToolResult:
    """The normalized result of one tool call in the baseline."""

    tool_name: str
    status: ToolStatus
    output: str = ""
    operation_key: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def as_dict(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "output": self.output,
            "operation_key": self.operation_key,
            "error": self.error,
        }


@dataclass
class RunMetrics:
    """Session 1 measurements for tool usage and repeated work."""

    tool_call_count: int = 0
    successful_tool_call_count: int = 0
    failed_tool_call_count: int = 0
    repeated_work_count: int = 0
    _seen_operation_keys: set[str] = field(default_factory=set, repr=False)

    def record_tool_call(self, result: ToolResult) -> None:
        self.tool_call_count += 1
        if result.succeeded:
            self.successful_tool_call_count += 1
        else:
            self.failed_tool_call_count += 1

        operation_key = result.operation_key or result.tool_name
        if operation_key in self._seen_operation_keys:
            self.repeated_work_count += 1
        self._seen_operation_keys.add(operation_key)

    @classmethod
    def aggregate(cls, metrics: Iterable["RunMetrics"]) -> "RunMetrics":
        """Aggregate independent runs without treating cases as one run."""

        aggregate = cls()
        for metric in metrics:
            aggregate.tool_call_count += metric.tool_call_count
            aggregate.successful_tool_call_count += (
                metric.successful_tool_call_count
            )
            aggregate.failed_tool_call_count += metric.failed_tool_call_count
            aggregate.repeated_work_count += metric.repeated_work_count
        return aggregate

    @property
    def tool_success_rate(self) -> float:
        if self.tool_call_count == 0:
            return 0.0
        return round(
            self.successful_tool_call_count / self.tool_call_count,
            3,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "tool_call_count": self.tool_call_count,
            "successful_tool_call_count": self.successful_tool_call_count,
            "failed_tool_call_count": self.failed_tool_call_count,
            "tool_success_rate": self.tool_success_rate,
            "repeated_work_count": self.repeated_work_count,
        }


@dataclass(frozen=True)
class TaskRunResult:
    """Observable result of one Reactive baseline run."""

    run_id: str
    task: TaskSpec
    classification: TaskClassification
    status: RunStatus
    output: str
    tool_results: tuple[ToolResult, ...]
    metrics: RunMetrics

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "task": {
                "task_id": self.task.task_id,
                "objective": self.task.objective,
                "workdir": str(self.task.workdir),
            },
            "classification": self.classification.as_dict(),
            "status": self.status,
            "output": self.output,
            "tool_results": [result.as_dict() for result in self.tool_results],
            "metrics": self.metrics.as_dict(),
        }


@dataclass(frozen=True)
class CaseRunResult:
    """One fixed case paired with its Reactive baseline result."""

    case: TaskCase
    result: TaskRunResult

    @property
    def classification_matches(self) -> bool:
        return self.case.matches(self.result.classification)

    def as_dict(self) -> dict[str, object]:
        return {
            "case": self.case.as_dict(),
            "result": self.result.as_dict(),
            "classification_matches": self.classification_matches,
        }


@dataclass(frozen=True)
class BatchRunResult:
    """Observable report for a fixed set of baseline cases."""

    case_runs: tuple[CaseRunResult, ...]
    metrics: RunMetrics

    @property
    def classification_match_count(self) -> int:
        return sum(case_run.classification_matches for case_run in self.case_runs)

    @property
    def classification_accuracy(self) -> float:
        if not self.case_runs:
            return 0.0
        return round(self.classification_match_count / len(self.case_runs), 3)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "reactive-baseline",
            "case_count": len(self.case_runs),
            "expected_planning_case_count": sum(
                case_run.case.planning_recommended for case_run in self.case_runs
            ),
            "actual_planning_case_count": sum(
                case_run.result.classification.planning_recommended
                for case_run in self.case_runs
            ),
            "classification_match_count": self.classification_match_count,
            "classification_accuracy": self.classification_accuracy,
            "metrics": self.metrics.as_dict(),
            "cases": [case_run.as_dict() for case_run in self.case_runs],
        }
