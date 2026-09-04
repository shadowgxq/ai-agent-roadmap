"""W16 Session 1 Reactive single-agent baseline."""

from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from ..classification import classify_task
from ..contracts import (
    BatchRunResult,
    CaseRunResult,
    RunMetrics,
    TaskCase,
    TaskRunResult,
    TaskSpec,
    ToolResult,
)
from ..tools.repository import list_repository


RepositoryTool = Callable[[Path], ToolResult]


class ReactiveBaseline:
    """Run one repository tool and return its result without a Planner."""

    def __init__(self, repository_tool: RepositoryTool = list_repository) -> None:
        self._repository_tool = repository_tool

    def run(self, task: TaskSpec) -> TaskRunResult:
        """Classify the task, execute exactly one tool, and expose metrics."""

        classification = classify_task(task.objective)
        metrics = RunMetrics()
        try:
            tool_result = self._repository_tool(task.workdir)
        except Exception as exc:  # noqa: BLE001 - normalize tool failures.
            tool_result = ToolResult(
                tool_name=getattr(self._repository_tool, "__name__", "repository_tool"),
                status="failed",
                operation_key=f"tool:{task.task_id}",
                error=f"工具调用失败：{type(exc).__name__}: {exc}",
            )

        metrics.record_tool_call(tool_result)
        output = (
            tool_result.output
            if tool_result.succeeded
            else tool_result.error or "工具执行失败。"
        )
        return TaskRunResult(
            run_id=uuid4().hex,
            task=task,
            classification=classification,
            status="completed" if tool_result.succeeded else "failed",
            output=output,
            tool_results=(tool_result,),
            metrics=metrics,
        )

    def run_cases(
        self,
        cases: Iterable[TaskCase],
        workdir: Path,
    ) -> BatchRunResult:
        """Run fixed cases independently and return an aggregate baseline report."""

        case_runs = tuple(
            CaseRunResult(
                case=case,
                result=self.run(
                    TaskSpec(
                        objective=case.objective,
                        workdir=workdir,
                    )
                ),
            )
            for case in cases
        )
        return BatchRunResult(
            case_runs=case_runs,
            metrics=RunMetrics.aggregate(
                case_run.result.metrics for case_run in case_runs
            ),
        )
