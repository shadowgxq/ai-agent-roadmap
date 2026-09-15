"""W18 Session 4: bounded DAG execution with cooperative Worker adapters.

Use one executor per workspace. Workers receive (assignment, context); every
real tool call must go through context.call_tool(). Registered tool handlers
are trusted host adapters, not model-supplied callables. This is an in-process
scheduler, not an OS sandbox or a distributed exactly-once implementation.

Timeout revokes future tool calls; it cannot kill Python threads or undo a tool
already in flight. An unfinished attempt occupies its slot, and any uncertain
write quarantines the workspace until the caller supplies reconciliation evidence.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from threading import Lock
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

from .collaboration import (
    CollaborationPlan, CollaborationTrace, Manager, ManagerDecision,
    SideEffectStatus, WorkerAssignment, WorkerResult, WorkerStatus,
)
from .decision import WorkerRole
from .dependency import DependencyGraph


class ExecutionError(ValueError):
    """Invalid execution configuration or unsafe lifecycle operation."""


class WorkerTimeoutError(TimeoutError):
    """The attempt deadline expired or its tool authority was revoked."""


class WorkerBudgetExceeded(ExecutionError):
    """A tool call was refused before spending beyond a budget."""


def _integer(value: int, name: str, minimum: int = 1) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ExecutionError(f"{name} 必须是 >= {minimum} 的整数。")


def _seconds(value: float, name: str, minimum: float = 0.0) -> None:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < minimum):
        raise ExecutionError(f"{name} 必须是 >= {minimum} 的有限数值。")


@dataclass(frozen=True)
class ExecutionLimits:
    max_concurrency: int = 3
    per_worker_timeout: float | None = None
    per_worker_tool_budget: int | None = None
    total_task_budget: int = 12  # All submitted attempts, including retries.
    total_tool_budget: int = 144  # Includes failed calls and every attempt.
    timeout_grace_seconds: float = 0.05

    def __post_init__(self) -> None:
        for name in ("max_concurrency", "total_task_budget", "total_tool_budget"):
            _integer(getattr(self, name), name)
        if self.per_worker_tool_budget is not None:
            _integer(self.per_worker_tool_budget, "per_worker_tool_budget")
        if self.per_worker_timeout is not None:
            _seconds(self.per_worker_timeout, "per_worker_timeout")
            if self.per_worker_timeout == 0:
                raise ExecutionError("per_worker_timeout 必须大于 0。")
        _seconds(self.timeout_grace_seconds, "timeout_grace_seconds")

    def timeout_for(self, assignment: WorkerAssignment) -> float:
        return min(assignment.role_spec.timeout_seconds,
                   self.per_worker_timeout or assignment.role_spec.timeout_seconds)

    def tool_budget_for(self, assignment: WorkerAssignment) -> int:
        return min(assignment.role_spec.max_tool_calls,
                   self.per_worker_tool_budget or assignment.role_spec.max_tool_calls)


@dataclass(frozen=True)
class WorkerTool:
    """Host-registered tool; effect classification must be trustworthy."""

    handler: Callable[..., object]
    effect: Literal["read", "write", "verify"]

    def __post_init__(self) -> None:
        if not callable(self.handler) or self.effect not in ("read", "write", "verify"):
            raise ExecutionError("工具必须包含 callable handler 和明确的 effect。")


@dataclass
class _ToolLedger:
    limit: int
    used: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def reserve(self) -> None:
        with self.lock:
            if self.used >= self.limit:
                raise WorkerBudgetExceeded("总工具调用预算已耗尽。")
            self.used += 1


class WorkerContext:
    """Attempt-local evidence, identity, tool budget, and revocable authority.

    Handlers run synchronously. Do not detach work or perform direct I/O in a
    runner: cancellation, permission and budget guarantees apply at this gateway.
    The host adapter must also constrain file paths and terminate child processes.
    """

    def __init__(
        self, assignment: WorkerAssignment, attempt_id: str, attempt_number: int,
        dependencies: Mapping[str, WorkerResult], tools: Mapping[str, WorkerTool],
        ledger: _ToolLedger, deadline: float,
    ) -> None:
        self.assignment = assignment
        self.attempt_id = attempt_id
        self.attempt_number = attempt_number
        self.dependency_results = MappingProxyType(dict(dependencies))
        self.deadline = deadline
        self._tools = tools
        self._ledger = ledger
        self._lock = Lock()
        self._revoked = False
        self._calls: list[str] = []
        self._inflight = 0
        self._effect: SideEffectStatus = "none"
        self._denial: str | None = None

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(ref for result in self.dependency_results.values()
                                   for ref in result.evidence_refs))

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True

    def snapshot(self) -> tuple[tuple[str, ...], SideEffectStatus, int, str | None]:
        with self._lock:
            return tuple(self._calls), self._effect, self._inflight, self._denial

    def call_tool(self, name: str, *args: object, **kwargs: object) -> object:
        with self._lock:
            if self._revoked or time.monotonic() >= self.deadline:
                self._revoked = True
                raise WorkerTimeoutError("attempt 已超时或工具权限已撤销。")
            tool = self._tools.get(name)
            allowed = self.assignment.role_spec.boundary.tool_allowlist
            if tool is None or name not in allowed:
                self._denial = f"工具未授权：{name}"
                self._revoked = True
                raise PermissionError(self._denial)
            boundary = self.assignment.role_spec.boundary
            if ((tool.effect == "write" and not boundary.can_write)
                    or (tool.effect == "verify" and self.assignment.role != "tester")
                    or (self.assignment.role == "researcher" and tool.effect != "read")):
                self._denial = f"工具 effect 越过角色边界：{name}"
                self._revoked = True
                raise PermissionError(self._denial)
            if self._inflight:
                self._denial = "同一 Worker 不允许脱离调度器并发调用工具。"
                self._revoked = True
                raise ExecutionError(self._denial)
            try:
                if len(self._calls) >= self.assignment.role_spec.max_tool_calls:
                    raise WorkerBudgetExceeded("单 Worker 工具调用预算已耗尽。")
                self._ledger.reserve()
            except WorkerBudgetExceeded as exc:
                self._denial = str(exc)
                self._revoked = True
                raise
            self._calls.append(f"{self.attempt_id}:tool:{len(self._calls) + 1}:{name}")
            self._inflight += 1
            previous_effect = self._effect
            if tool.effect != "read":
                self._effect = "unknown"  # Set BEFORE the host performs the write.
        succeeded = False
        try:
            value = tool.handler(*args, **kwargs)
            succeeded = True
            return value
        finally:
            with self._lock:
                self._inflight -= 1
                if tool.effect != "read" and succeeded and previous_effect != "unknown":
                    self._effect = "applied"

    def result(
        self, summary: str, *, status: WorkerStatus = "succeeded",
        evidence_refs: tuple[str, ...] = (), recommendation: str = "",
        changed_files: tuple[str, ...] = (), failure_reason: str | None = None,
    ) -> WorkerResult:
        calls, effect, inflight, _ = self.snapshot()
        return WorkerResult(
            assignment_id=self.assignment.assignment_id, task_id=self.assignment.task_id,
            role=self.assignment.role, status=status, summary=summary,
            evidence_refs=evidence_refs, recommendation=recommendation,
            changed_files=changed_files, failure_reason=failure_reason,
            attempt_id=self.attempt_id, attempt_number=self.attempt_number,
            idempotency_key=self.assignment.idempotency_key, tool_call_ids=calls,
            side_effect_status=effect, outcome_known=effect != "unknown" and not inflight,
        )


WorkerRunner = Callable[[WorkerAssignment, WorkerContext], WorkerResult]


@dataclass(frozen=True)
class WorkerReplacement:
    worker_id: str
    role: WorkerRole
    runner: WorkerRunner

    def __post_init__(self) -> None:
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise ExecutionError("replacement.worker_id 必须是非空字符串。")
        if self.role not in ("researcher", "coder", "tester") or not callable(self.runner):
            raise ExecutionError("replacement 必须指定 Worker role 和 callable runner。")


ReassignSelector = (
    Mapping[str, WorkerReplacement]
    | Callable[[WorkerAssignment, WorkerResult], WorkerReplacement | None]
)


@dataclass(frozen=True)
class WorkerAttempt:
    assignment: WorkerAssignment
    result: WorkerResult
    attempt_id: str
    attempt_number: int
    elapsed_seconds: float
    timed_out: bool = False
    side_effect_possible: bool = False
    safe_to_retry: bool = False
    worker_id: str = "primary"
    stopped: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment.assignment_id, "task_id": self.result.task_id,
            "attempt_id": self.attempt_id, "attempt_number": self.attempt_number,
            "worker_id": self.worker_id, "elapsed_seconds": self.elapsed_seconds,
            "timed_out": self.timed_out, "stopped": self.stopped,
            "side_effect_possible": self.side_effect_possible,
            "safe_to_retry": self.safe_to_retry, "result": self.result.as_dict(),
        }


class ResultAggregationError(ExecutionError):
    """Invalid identity, version or conflicting duplicate delivery."""


class TaskResultAggregator:
    """One final result per task; execution registers authorized attempts first.

    from_results() accepts a trusted collection of final results. Neither mode
    resolves semantic disagreements; that is Session 5's separate concern.
    """

    def __init__(self) -> None:
        self._latest: dict[str, WorkerResult] = {}
        self._expected: dict[str, tuple[str, WorkerRole, int, str]] = {}

    def begin(self, assignment: WorkerAssignment, number: int, attempt_id: str) -> None:
        _integer(number, "attempt_number")
        previous = self._expected.get(assignment.task_id)
        if previous is not None and number <= previous[2]:
            raise ResultAggregationError("新 attempt 必须使用更高的版本号。")
        self._expected[assignment.task_id] = (
            assignment.assignment_id, assignment.role, number, attempt_id,
        )
        self._latest.pop(assignment.task_id, None)

    def add(self, result: WorkerResult) -> bool:
        if not isinstance(result, WorkerResult) or result.status in ("assigned", "running"):
            raise ResultAggregationError("只聚合 WorkerResult 最终状态。")
        expected = self._expected.get(result.task_id)
        if self._expected and expected is None:
            raise ResultAggregationError("结果 task_id 未注册。")
        if expected is not None:
            if result.attempt_number < expected[2]:
                return False
            if (result.assignment_id, result.role, result.attempt_number,
                    result.attempt_id) != expected:
                raise ResultAggregationError("结果不是 Manager 授权的当前 attempt。")
        previous = self._latest.get(result.task_id)
        if previous is not None:
            if (previous.assignment_id, previous.role) != (result.assignment_id, result.role):
                raise ResultAggregationError("同一 task_id 的 assignment/role 不一致。")
            if result.attempt_number < previous.attempt_number:
                return False
            if result.attempt_number == previous.attempt_number:
                if result != previous:
                    raise ResultAggregationError("同一 attempt 出现不同的最终结果。")
                return False
        self._latest[result.task_id] = result
        return True

    record = add
    accept = add

    @classmethod
    def from_results(cls, results: Iterable[WorkerResult]) -> TaskResultAggregator:
        instance = cls()
        for result in results:
            instance.add(result)
        return instance

    def get(self, task_id: str) -> WorkerResult | None:
        return self._latest.get(task_id)

    @property
    def results(self) -> tuple[WorkerResult, ...]:
        return tuple(self._latest[key] for key in sorted(self._latest))

    @property
    def by_task_id(self) -> Mapping[str, WorkerResult]:
        return dict(self._latest)

    def __len__(self) -> int:
        return len(self._latest)

    def as_dict(self) -> dict[str, object]:
        return {result.task_id: result.as_dict() for result in self.results}


class SafeRetryPolicy:
    def __init__(self, manager: Manager | None = None, *, max_retries: int = 1) -> None:
        _integer(max_retries, "max_retries", 0)
        self.manager = manager or Manager(max_retries=max_retries)
        self.max_retries = self.manager.max_retries

    def is_safe_to_retry(
        self, assignment: WorkerAssignment, result: WorkerResult, *, timed_out: bool = False,
    ) -> bool:
        return (result.side_effect_status == "none" and result.outcome_known
                and (not timed_out or assignment.role == "researcher"))

    def decide(
        self, assignment: WorkerAssignment, result: WorkerResult, *, retry_count: int = 0,
        reassign_to: WorkerRole | None = None, timed_out: bool = False, stopped: bool = True,
    ) -> ManagerDecision:
        _integer(retry_count, "retry_count", 0)
        if not stopped:
            return ManagerDecision(assignment.assignment_id, "wait",
                                   "旧 Worker 尚未停止；保持占用，不创建替代 attempt。", retry_count)
        if result.status == "failed" and not self.is_safe_to_retry(
            assignment, result, timed_out=timed_out,
        ):
            return ManagerDecision(assignment.assignment_id, "pause",
                                   "先核对副作用；不能凭 idempotency_key 盲目重放。", retry_count)
        return self.manager.evaluate_result(result, retry_count=retry_count,
                                            reassign_to=reassign_to)


ExecutionTerminalStatus = Literal["completed", "blocked", "failed"]


@dataclass(frozen=True)
class WorkerExecutionReport:
    status: ExecutionTerminalStatus
    attempts: tuple[WorkerAttempt, ...]
    results: tuple[WorkerResult, ...]
    decisions: tuple[ManagerDecision, ...]
    completed_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    failed_task_ids: tuple[str, ...]
    critical_path: tuple[str, ...]
    wall_clock_seconds: float
    peak_concurrency: int
    total_attempts: int
    total_tool_calls: int = 0
    run_id: str = ""
    outstanding_attempt_ids: tuple[str, ...] = ()
    workspace_quarantined: bool = False
    blocked_reasons: Mapping[str, str] = field(default_factory=dict)

    @property
    def results_by_task_id(self) -> Mapping[str, WorkerResult]:
        return {result.task_id: result for result in self.results}

    @property
    def timed_out_task_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(a.result.task_id for a in self.attempts if a.timed_out))

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id, "status": self.status,
            "attempts": [item.as_dict() for item in self.attempts],
            "results": [item.as_dict() for item in self.results],
            "decisions": [item.as_dict() for item in self.decisions],
            "completed_task_ids": list(self.completed_task_ids),
            "blocked_task_ids": list(self.blocked_task_ids),
            "failed_task_ids": list(self.failed_task_ids),
            "critical_path": list(self.critical_path),
            "wall_clock_seconds": self.wall_clock_seconds,
            "peak_concurrency": self.peak_concurrency, "total_attempts": self.total_attempts,
            "total_tool_calls": self.total_tool_calls,
            "outstanding_attempt_ids": list(self.outstanding_attempt_ids),
            "workspace_quarantined": self.workspace_quarantined,
            "blocked_reasons": dict(self.blocked_reasons),
        }


@dataclass(frozen=True)
class _Returned:
    result: object
    error: Exception | None
    finished_at: float


@dataclass
class _Live:
    assignment: WorkerAssignment
    context: WorkerContext
    worker: WorkerReplacement
    started_at: float
    abandoned: bool = False


class ParallelWorkerExecutor:
    """Event-driven scheduling; no wave barrier and no unbounded submission queue."""

    def __init__(
        self, limits: ExecutionLimits | None = None, *, max_concurrency: int | None = None,
        per_worker_timeout: float | None = None, per_worker_tool_budget: int | None = None,
        total_task_budget: int | None = None, manager: Manager | None = None,
        retry_policy: SafeRetryPolicy | None = None, trace: CollaborationTrace | None = None,
        tools: Mapping[str, WorkerTool] | None = None,
    ) -> None:
        overrides = (max_concurrency, per_worker_timeout, per_worker_tool_budget, total_task_budget)
        if limits is not None and any(value is not None for value in overrides):
            raise ExecutionError("limits 与独立预算参数不能同时指定。")
        self.limits = limits or ExecutionLimits(
            max_concurrency=3 if max_concurrency is None else max_concurrency,
            per_worker_timeout=per_worker_timeout, per_worker_tool_budget=per_worker_tool_budget,
            total_task_budget=12 if total_task_budget is None else total_task_budget,
        )
        self.manager = manager or (retry_policy.manager if retry_policy else Manager())
        if retry_policy is not None and retry_policy.manager is not self.manager:
            raise ExecutionError("executor 和 retry_policy 必须共享 Manager。")
        self.retry_policy = retry_policy or SafeRetryPolicy(self.manager)
        self.trace = trace
        registered = dict(tools or {})
        if any(not isinstance(name, str) or not name.strip() or not isinstance(tool, WorkerTool)
               for name, tool in registered.items()):
            raise ExecutionError("tools 必须按名称注册 WorkerTool。")
        self._tools = MappingProxyType(registered)
        self._pool = ThreadPoolExecutor(max_workers=self.limits.max_concurrency)
        self._live: dict[Future[_Returned], _Live] = {}
        self._run_lock = Lock()
        self._counter_lock = Lock()
        self._active_workers = 0
        self._peak_concurrency = 0
        self._workspace_tainted = False
        self._closed = False

    def _enter_control(self) -> None:
        if not self._run_lock.acquire(blocking=False):
            raise ExecutionError("同一个 workspace executor 不能并发启动两个控制流程。")

    def close(self, *, wait: bool = False) -> None:
        self._enter_control()
        try:
            for live in self._live.values():
                live.context.revoke()
            self._pool.shutdown(wait=wait, cancel_futures=True)
            self._closed = True
        finally:
            self._run_lock.release()

    def __enter__(self) -> ParallelWorkerExecutor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close(wait=False)

    def wait_for_idle(self, timeout: float = 0.0) -> bool:
        """Wait without launching retries; late results never unlock dependencies."""
        _seconds(timeout, "timeout")
        self._enter_control()
        try:
            if self._live:
                wait(tuple(self._live), timeout=timeout)
            self._reap_abandoned()
            return not self._live
        finally:
            self._run_lock.release()

    def acknowledge_reconciliation(self, *, evidence_refs: tuple[str, ...]) -> None:
        """Caller attests that changed files/external effects were actually reconciled."""
        if (not isinstance(evidence_refs, tuple) or not evidence_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs)):
            raise ExecutionError("解除工作区隔离必须提供实际 reconciliation evidence。")
        self._enter_control()
        try:
            self._reap_abandoned()
            if self._live:
                raise ExecutionError("旧 Worker 或工具仍在运行，不能解除隔离。")
            self._workspace_tainted = False
        finally:
            self._run_lock.release()

    def execute(
        self, plan_or_graph: CollaborationPlan | DependencyGraph | Iterable[WorkerAssignment],
        runner: WorkerRunner, *, reassign_to: ReassignSelector | None = None,
    ) -> WorkerExecutionReport:
        self._enter_control()
        try:
            self._reap_abandoned()
            if self._closed or self._workspace_tainted or self._live:
                raise ExecutionError("executor 已关闭、工作区待核对或旧 Worker 未停止。")
            if not callable(runner):
                raise ExecutionError("runner 必须可调用。")
            graph = (plan_or_graph if isinstance(plan_or_graph, DependencyGraph)
                     else DependencyGraph(plan_or_graph))
            self._validate_tools(graph)
            return self._execute(graph, runner, reassign_to)
        finally:
            # Covers unexpected controller errors as well as normal timeout exits.
            for future, live in self._live.items():
                live.abandoned = True
                live.context.revoke()
                future.cancel()
                if live.assignment.role != "researcher":
                    self._workspace_tainted = True
            self._run_lock.release()

    run = execute

    def execute_parallel(
        self, assignments: Iterable[WorkerAssignment], runner: WorkerRunner,
    ) -> tuple[WorkerAttempt, ...]:
        candidates = tuple(assignments)
        if not candidates:
            return ()
        graph = DependencyGraph(candidates)
        if (any(item.dependencies for item in candidates)
                or len(graph.safe_parallel_group(candidates)) != len(candidates)):
            raise ExecutionError("execute_parallel 仅接收无依赖且资源安全的只读任务。")
        if len(graph) > self.limits.total_task_budget:
            raise ExecutionError("任务数超过 total_task_budget。")
        return self.execute(graph, runner).attempts

    def _execute(
        self, graph: DependencyGraph, runner: WorkerRunner, selector: ReassignSelector | None,
    ) -> WorkerExecutionReport:
        started = time.monotonic()
        run_id = uuid4().hex
        ledger = _ToolLedger(self.limits.total_tool_budget)
        aggregator = TaskResultAggregator()
        attempts: list[WorkerAttempt] = []
        decisions: list[ManagerDecision] = []
        completed: set[str] = set()
        pending = set(graph.assignment_ids)
        blocked: dict[str, str] = {}
        running: dict[Future[_Returned], _Live] = {}
        numbers = {key: 0 for key in graph.assignment_ids}
        workers = {item.assignment_id: WorkerReplacement("primary", item.role, runner)
                   for item in graph.assignments}
        submitted = 0
        self._peak_concurrency = 0

        while pending or running:
            self._reap_abandoned()
            if self._workspace_tainted:
                blocked.update({key: "共享工作区等待副作用核对。" for key in pending})
                pending.clear()
            # Reserve one attempt for each remaining node before spending retries.
            remaining = self.limits.total_task_budget - submitted
            if pending and remaining < len(pending):
                blocked.update({key: "剩余预算不足以完成依赖链。" for key in pending})
                pending.clear()
            if pending and ledger.used >= ledger.limit:
                blocked.update({key: "总工具预算已耗尽。" for key in pending})
                pending.clear()

            running_ids = {live.assignment.assignment_id for live in running.values()}
            ready = graph.ready(completed, running_ids=running_ids, blocked_ids=blocked)
            for assignment in ready:
                if assignment.assignment_id not in pending or len(self._live) >= self.limits.max_concurrency:
                    continue
                occupied = tuple(live.assignment for live in self._live.values())
                if occupied and not all(graph.can_run_in_parallel(assignment, other) for other in occupied):
                    continue
                dependencies = {graph.get(key).task_id: aggregator.get(graph.get(key).task_id)
                                for key in assignment.dependencies}
                if any(value is None or value.status != "succeeded" for value in dependencies.values()):
                    raise ExecutionError("已完成依赖缺少已接受结果。")
                number = numbers[assignment.assignment_id] + 1
                numbers[assignment.assignment_id] = number
                bounded = replace(assignment, role_spec=replace(
                    assignment.role_spec, timeout_seconds=self.limits.timeout_for(assignment),
                    max_tool_calls=self.limits.tool_budget_for(assignment),
                ), status="running")
                attempt_started = time.monotonic()
                context = WorkerContext(bounded, f"{run_id}:{assignment.task_id}:{number}", number,
                                        dependencies, self._tools, ledger,
                                        attempt_started + bounded.role_spec.timeout_seconds)
                aggregator.begin(assignment, number, context.attempt_id)
                worker = workers[assignment.assignment_id]
                live = _Live(bounded, context, worker, attempt_started)
                if self.trace is not None:
                    self.trace.record_assignment(bounded)
                future = self._pool.submit(self._invoke, live)
                self._live[future] = live
                running[future] = live
                submitted += 1
                pending.remove(assignment.assignment_id)

            if not running:
                if pending:
                    reason = "旧 Worker 未停止，保持并发占用。" if self._live else "依赖失败或被阻塞。"
                    blocked.update({key: reason for key in pending})
                    pending.clear()
                break
            next_deadline = min(live.context.deadline for live in running.values())
            wait(tuple(running), timeout=max(0.0, next_deadline - time.monotonic()),
                 return_when=FIRST_COMPLETED)
            now = time.monotonic()
            finished = [future for future, live in running.items()
                        if future.done() or now >= live.context.deadline]
            for future in finished:
                live = running.pop(future)
                attempt = self._finish(future, live)
                attempts.append(attempt)
                aggregator.add(attempt.result)
                replacement = None
                try:
                    if (attempt.result.status == "failed" and attempt.safe_to_retry
                            and attempt.attempt_number <= self.retry_policy.max_retries):
                        replacement = self._select_reassign(attempt, live.worker, selector)
                    decision = self.retry_policy.decide(
                        live.assignment, attempt.result, retry_count=attempt.attempt_number - 1,
                        reassign_to=replacement.role if replacement else None,
                        timed_out=attempt.timed_out, stopped=attempt.stopped,
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    decision = ManagerDecision(live.assignment.assignment_id, "pause",
                                               f"恢复决策无效：{exc}", attempt.attempt_number - 1)
                key = live.assignment.assignment_id
                if decision.action == "accept":
                    completed.add(key)
                elif decision.action in ("retry", "reassign"):
                    pending.add(key)
                    if replacement is not None:
                        workers[key] = replacement
                else:
                    blocked[key] = decision.reason
                if self._requires_workspace_block(attempt, decision):
                    self._workspace_tainted = True
                decisions.append(decision)
                if self.trace is not None:
                    self.trace.record_result(attempt.result)
                    self.trace.record_decision(decision)

        results = aggregator.results
        return WorkerExecutionReport(
            status="completed" if len(completed) == len(graph) else "blocked",
            attempts=tuple(attempts), results=results, decisions=tuple(decisions),
            completed_task_ids=tuple(item.task_id for item in graph if item.assignment_id in completed),
            blocked_task_ids=tuple(item.task_id for item in graph if item.assignment_id in blocked),
            failed_task_ids=tuple(item.task_id for item in results if item.status == "failed"),
            critical_path=graph.critical_path(), wall_clock_seconds=time.monotonic() - started,
            peak_concurrency=self._peak_concurrency, total_attempts=submitted,
            total_tool_calls=ledger.used, run_id=run_id,
            outstanding_attempt_ids=tuple(live.context.attempt_id for live in self._live.values()),
            workspace_quarantined=self._workspace_tainted,
            blocked_reasons={graph.get(key).task_id: reason for key, reason in blocked.items()},
        )

    def _invoke(self, live: _Live) -> _Returned:
        with self._counter_lock:
            self._active_workers += 1
            self._peak_concurrency = max(self._peak_concurrency, self._active_workers)
        try:
            try:
                result = live.worker.runner(live.assignment, live.context)
                return _Returned(result, None, time.monotonic())
            except Exception as exc:
                return _Returned(None, exc, time.monotonic())
        finally:
            live.context.revoke()
            with self._counter_lock:
                self._active_workers -= 1

    def _finish(self, future: Future[_Returned], live: _Live) -> WorkerAttempt:
        context = live.context
        returned = future.result() if future.done() and not future.cancelled() else None
        timed_out = returned is None or returned.finished_at > context.deadline
        if returned is not None and isinstance(returned.error, WorkerTimeoutError):
            timed_out = True
        context.revoke()
        if timed_out and not future.done():
            future.cancel()
            wait((future,), timeout=self.limits.timeout_grace_seconds)
        calls, effect, inflight, denial = context.snapshot()
        stopped = future.done() and inflight == 0
        if timed_out:
            if live.assignment.role != "researcher":
                effect = "unknown"
            if stopped and not future.cancelled():
                late = future.result().result
                if isinstance(late, WorkerResult) and (
                    late.changed_files or late.side_effect_status != "none" or not late.outcome_known
                ):
                    effect = "unknown"
            result = context.result("Worker 超时。", status="failed",
                                    failure_reason="worker_timeout")
        elif returned is None or returned.error is not None:
            error = returned.error if returned else ExecutionError("Worker 未返回结果。")
            message = f"{type(error).__name__}: {error}"
            result = context.result(f"Worker 失败：{message}",
                                    status="blocked" if denial else "failed", failure_reason=message)
        else:
            raw = returned.result
            if isinstance(raw, WorkerResult):
                identity = (raw.assignment_id, raw.task_id, raw.role, raw.attempt_id,
                            raw.attempt_number, raw.idempotency_key)
                expected = (live.assignment.assignment_id, live.assignment.task_id,
                            live.assignment.role, context.attempt_id, context.attempt_number,
                            live.assignment.idempotency_key)
                violation = None
                if identity != expected:
                    violation = "结果身份或 attempt 与授权不一致。"
                elif raw.status in ("assigned", "running"):
                    violation = "runner 必须返回最终状态。"
                elif raw.tool_call_ids != calls:
                    violation = "工具计数必须来自受控调用入口。"
                elif raw.changed_files and not live.assignment.role_spec.boundary.can_write:
                    violation = "非写角色报告了文件修改。"
                elif live.assignment.role == "researcher" and raw.side_effect_status != "none":
                    violation = "Researcher 越过只读边界。"
                if raw.side_effect_status == "unknown" or not raw.outcome_known:
                    effect = "unknown"
                elif raw.changed_files or raw.side_effect_status == "applied":
                    effect = "applied" if effect != "unknown" else effect
                result = (context.result(violation, status="blocked", failure_reason=violation)
                          if violation else raw)
            else:
                result = context.result("runner 未返回 WorkerResult。", status="blocked",
                                        failure_reason="invalid_worker_result")
        if denial or inflight:
            reason = denial or "Worker 返回时工具仍未结束。"
            result = replace(result, status="blocked", failure_reason=reason, summary=reason)
        result = replace(result, tool_call_ids=calls, side_effect_status=effect,
                         outcome_known=effect != "unknown" and not inflight)
        safe = stopped and self.retry_policy.is_safe_to_retry(
            live.assignment, result, timed_out=timed_out,
        )
        if stopped:
            self._live.pop(future, None)
        else:
            live.abandoned = True
        return WorkerAttempt(
            live.assignment, result, context.attempt_id, context.attempt_number,
            max(0.0, (returned.finished_at if returned else time.monotonic()) - live.started_at),
            timed_out=timed_out, side_effect_possible=effect != "none", safe_to_retry=safe,
            worker_id=live.worker.worker_id, stopped=stopped,
        )

    @staticmethod
    def _requires_workspace_block(attempt: WorkerAttempt, decision: ManagerDecision) -> bool:
        return (decision.action != "accept" and
                (attempt.result.side_effect_status != "none" or not attempt.result.outcome_known
                 or (not attempt.stopped and attempt.assignment.role != "researcher")))

    @staticmethod
    def _select_reassign(
        attempt: WorkerAttempt, current: WorkerReplacement, selector: ReassignSelector | None,
    ) -> WorkerReplacement | None:
        if selector is None:
            return None
        try:
            replacement = (selector(attempt.assignment, attempt.result) if callable(selector)
                           else selector.get(attempt.result.task_id))
        except Exception as exc:
            raise ExecutionError(f"改派选择失败：{exc}") from exc
        if replacement is None:
            return None
        if not isinstance(replacement, WorkerReplacement):
            raise ExecutionError("reassign 必须返回具体 WorkerReplacement。")
        if (replacement.role != current.role or replacement.worker_id == current.worker_id
                or replacement.runner == current.runner):
            raise ExecutionError("必须更换同角色的不同 Worker 实例，不能改角色或只换名字。")
        return replacement

    def _validate_tools(self, graph: DependencyGraph) -> None:
        for assignment in graph:
            for name in assignment.role_spec.boundary.tool_allowlist:
                tool = self._tools.get(name)
                if tool is None:
                    continue  # Missing tools are denied if actually requested.
                if ((assignment.role == "researcher" and tool.effect != "read")
                        or (tool.effect == "write" and not assignment.role_spec.boundary.can_write)
                        or (tool.effect == "verify" and assignment.role != "tester")):
                    raise ExecutionError(f"{assignment.role} 工具白名单含越权能力：{name}")

    def _reap_abandoned(self) -> None:
        for future, live in tuple(self._live.items()):
            if not live.abandoned or not future.done() or live.context.snapshot()[2]:
                continue
            _, effect, _, _ = live.context.snapshot()
            if effect != "none":
                self._workspace_tainted = True
            if not future.cancelled():
                returned = future.result()
                if isinstance(returned.result, WorkerResult):
                    raw = returned.result
                    if raw.changed_files or raw.side_effect_status != "none" or not raw.outcome_known:
                        self._workspace_tainted = True
            del self._live[future]


# Compatibility names for the Session 4 public API.
ConcurrencyLimits = ExecutionBudget = ExecutionLimits
WorkerExecution = WorkerAttempt
ResultAggregator = TaskResultAggregator
RetryPolicy = RetrySafetyPolicy = SafeRetryPolicy
ExecutionReport = WorkerExecutionReport
WorkerExecutor = DependencyExecutor = ParallelWorkerExecutor

__all__ = [
    "ConcurrencyLimits", "DependencyExecutor", "ExecutionBudget", "ExecutionError",
    "ExecutionLimits", "ExecutionReport", "ExecutionTerminalStatus", "ParallelWorkerExecutor",
    "ReassignSelector", "ResultAggregationError", "ResultAggregator", "RetryPolicy",
    "RetrySafetyPolicy", "SafeRetryPolicy", "TaskResultAggregator", "WorkerAttempt",
    "WorkerBudgetExceeded", "WorkerContext", "WorkerExecution", "WorkerExecutionReport",
    "WorkerExecutor", "WorkerReplacement", "WorkerRunner", "WorkerTimeoutError", "WorkerTool",
]
