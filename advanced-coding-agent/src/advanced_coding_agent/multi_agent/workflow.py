"""W18 application entry point: Goal → route → execute → investigate → write.

Verification is deliberately deferred. A completed tool workflow is reported as
pending_verification, never as independently verified success or measured eval.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..long_horizon.goal import Goal
from ..planning.model import StructuredPlanModel
from .adapters import JsonModel, ModelWorker, RepositoryTools
from .aggregation import EvidenceAggregator
from .collaboration import CollaborationTrace, Manager, ManagerDecision, WorkerAssignment
from .decision import BaselineSpec, DeterministicSplitDecider, ParallelTaskCandidate, SplitProfile
from .execution import ExecutionLimits, ParallelWorkerExecutor, WorkerReplacement
from .routing import RouteRequest, RoutingTrace, StructuredRouter, TaskRouter


class ResearchTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1)
    context_scope: list[str] = Field(min_length=1, max_length=8)
    estimated_seconds: float = Field(gt=0, le=600, allow_inf_nan=False)
    independent: bool


class Decomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    complexity: Literal["simple", "complex"]
    research_tasks: list[ResearchTask] = Field(min_length=1, max_length=6)
    required_topics: list[str] = Field(min_length=1, max_length=6)
    serial_seconds: float = Field(ge=0, le=3600, allow_inf_nan=False)
    coordination_seconds: float = Field(ge=0, le=600, allow_inf_nan=False)


DECOMPOSE_PROMPT = """你是 Manager。拆分只读研究任务，声明真实依赖；
只有不需要其他研究任务输出的任务才能 independent=true。不能仅因复杂而标记独立。
返回 {complexity: simple|complex, research_tasks:[{objective,context_scope:[路径或范围],
estimated_seconds:正数,independent:布尔}], required_topics:[需要证据支持的决策主题],
serial_seconds:串行阶段估算秒数, coordination_seconds:协调开销估算秒数}。
研究最多6项，主题最多6项；每个主题是一个互斥决策，避免混入多个不互斥事实。
不执行任务，不增加用户授权范围；估算不代表实测。"""


class MultiAgentWorkflow:
    def __init__(self, model: StructuredPlanModel, workdir: Path, *,
                 write_paths: tuple[str, ...] = (), max_concurrency: int = 3,
                 max_tool_calls: int = 96, max_attempts: int = 24,
                 max_model_calls: int = 100, max_investigation_rounds: int = 1) -> None:
        self.repository = RepositoryTools(workdir, write_paths=write_paths)
        self.model = JsonModel(model, max_model_calls)
        self.limits = ExecutionLimits(max_concurrency=max_concurrency,
                                      total_tool_budget=max_tool_calls,
                                      total_task_budget=max_attempts)
        self.aggregator = EvidenceAggregator(max_investigation_rounds=max_investigation_rounds)
        self.manager = Manager()
        self.trace = CollaborationTrace()
        self.routing_trace = RoutingTrace()
        self.router = TaskRouter(trace=self.routing_trace, structured=StructuredRouter(
            lambda request: self.model.ask(
                "返回 worker_role/reason/confidence/fallback，不能扩大修改权限。", request.as_dict())
        ))
        self.reports: list[dict] = []
        self.reviews: list[dict] = []
        self.recoveries: list[dict] = []
        self._used = False

    def _assignment(self, goal: Goal, task_id: str, objective: str, kind: str,
                    *, dependencies: tuple[str, ...] = (), context: tuple[str, ...] = ()) -> WorkerAssignment:
        request = RouteRequest(task_id, objective, kind=kind, constraints=goal.constraints,
                               input_context=context, requires_write=kind == "edit")
        route = self.router.route(request)
        if route.status != "routed":
            recovery = self.manager.recover_route(route)
            self.recoveries.append(recovery.as_dict())
            raise ValueError(recovery.reason)
        return WorkerAssignment(
            task_id, task_id, route.worker_role, objective, goal.constraints,
            (f"任务目标：{goal.objective}",
             *(f"验收条件（本轮不执行）：{c.description}" for c in goal.success_criteria), *context),
            dependencies, self.manager.role_spec(route.worker_role),
            write_targets=tuple(sorted(self.repository.write_paths)) if kind == "edit" else (),
        )

    def _execute(self, assignments, worker, *, initial_results=(), before_write=None,
                 concurrency: int | None = None):
        used_calls = sum(report["total_tool_calls"] for report in self.reports)
        used_attempts = sum(report["total_attempts"] for report in self.reports)
        remaining_calls = self.limits.total_tool_budget - used_calls
        remaining_attempts = self.limits.total_task_budget - used_attempts
        if remaining_calls <= 0 or remaining_attempts <= 0:
            raise ValueError("跨研究、调查和写入阶段的总预算已耗尽。")
        limits = replace(self.limits, total_tool_budget=remaining_calls,
                         total_task_budget=remaining_attempts,
                         max_concurrency=concurrency or self.limits.max_concurrency)
        replacement = worker.replacement() if isinstance(worker, ModelWorker) else None
        def select_replacement(assignment, result):
            return (WorkerReplacement("recovery", assignment.role, replacement)
                    if replacement is not None else None)
        with ParallelWorkerExecutor(limits, manager=self.manager, trace=self.trace,
                                    tools=self.repository.tools(), before_write=before_write) as executor:
            report = executor.execute(assignments, worker, initial_results=initial_results,
                                      reassign_to=select_replacement)
        self.reports.append(report.as_dict())
        return report

    def run(self, goal: Goal) -> dict:
        if self._used:
            raise ValueError("每个 workflow 实例只能运行一次，避免跨 Goal 上下文混用。")
        self._used = True
        started = time.monotonic()
        split = None
        status, reason = "blocked", "流程未完成。"
        try:
            decomposition = Decomposition.model_validate(self.model.ask(DECOMPOSE_PROMPT, {
                "goal": goal.as_dict(), "write_paths": sorted(self.repository.write_paths),
                "verification": "deferred",
            }))
            topics = tuple(dict.fromkeys(decomposition.required_topics))
            if any(not topic.strip() for topic in topics):
                raise ValueError("决策主题不能为空。")
            tasks = decomposition.research_tasks
            candidates = tuple(ParallelTaskCandidate(
                f"{goal.goal_id}:research:{index}", task.objective,
                task.estimated_seconds, tuple(task.context_scope),
            ) for index, task in enumerate(tasks)) if all(t.independent for t in tasks) else ()
            writable = bool(self.repository.write_paths)
            profile = SplitProfile(
                goal.goal_id, goal.objective, decomposition.complexity, candidates,
                ("code",) if writable else ("summarize",),
                decomposition.serial_seconds + (0 if candidates else sum(t.estimated_seconds for t in tasks)),
                decomposition.coordination_seconds,
                tuple(dict.fromkeys(scope for task in tasks for scope in task.context_scope)),
                (), writable, False, "low", tuple(sorted(self.repository.write_paths)), goal.constraints,
            )
            baseline = BaselineSpec(
                "interactive-workflow", "interactive-single-worker",
                getattr(self.model.model, "model", "injected-model"), 0,
                tuple(self.repository.tools()), self.limits.total_tool_budget, 32000, 3600,
                ("verified_success", "wall_clock_seconds"),
            )
            split = DeterministicSplitDecider().decide(profile, baseline)
            worker = ModelWorker(self.model, self.repository, topics)
            if split.mode == "single-agent":
                report = self._single(goal, worker, writable)
                if report.status == "completed":
                    status, reason = "pending_verification", "单 Worker 已完成工具流程，测试与最终验收待执行。"
                else:
                    reason = "单 Worker 执行受阻，详见 execution_reports。"
            else:
                status, reason = self._multi(goal, worker, tasks, topics, writable)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        return {
            "goal": goal.as_dict(), "status": status, "reason": reason,
            "summary": [result["summary"] for result in self.reports[-1]["results"]]
                       if self.reports else [],
            "split_decision": split.as_dict() if split else None,
            "verification": {"status": "not_run", "verified_success": False},
            "changed_files": sorted(self.repository.changed),
            "wall_clock_seconds": time.monotonic() - started,
            "model_calls": self.model.calls,
            "total_tool_calls": sum(r["total_tool_calls"] for r in self.reports),
            "routing": self.routing_trace.as_dict(), "route_recoveries": self.recoveries,
            "trace": self.trace.as_dict(), "execution_reports": self.reports,
            "aggregation_reports": self.reviews, "evidence": dict(self.repository.evidence),
            "measurement_scope": "interactive workflow; not a paired W17/W18 evaluation",
        }

    def _single(self, goal, worker, writable):
        assignment = self._assignment(goal, f"{goal.goal_id}:single", goal.objective,
                                      "edit" if writable else "search")
        if not writable:
            return self._execute((assignment,), worker, concurrency=1)
        # The host bootstrap records user authorization, not a second model Agent.
        # One model loop performs both investigation and editing in the single path.
        seed = self._assignment(goal, f"{goal.goal_id}:authorization", "记录宿主授权", "search")
        evidence = self.repository.record("authorization", {
            "goal": goal.as_dict(), "write_paths": sorted(self.repository.write_paths),
        })
        boundary = replace(assignment.role_spec.boundary,
                           tool_allowlist=tuple(self.repository.tools()))
        assignment = replace(assignment, dependencies=(seed.assignment_id,), role_spec=replace(
            assignment.role_spec, boundary=boundary,
            role_prompt="你是单 Agent；先读取研究证据，再在授权文件内完成最小修改。",
        ))
        def runner(item, context):
            if item.assignment_id == seed.assignment_id:
                return context.result("已记录用户目标与文件授权。", evidence_refs=(evidence["evidence_ref"],))
            return worker(item, context)
        def gate(item, dependencies):
            return ManagerDecision(item.assignment_id, "accept", "单 Agent 按明确文件授权执行。",
                                   accepted_evidence_refs=(evidence["evidence_ref"],))
        return self._execute((seed, assignment), runner, before_write=gate, concurrency=1)

    def _multi(self, goal, worker, tasks, topics, writable):
        previous_context: tuple[str, ...] = ()
        for round_number in range(self.aggregator.max_investigation_rounds + 1):
            assignments = tuple(self._assignment(
                goal, f"{goal.goal_id}:research:{round_number}:{index}", task.objective, "search",
                context=(f"限定研究范围：{', '.join(task.context_scope)}", *previous_context),
            ) for index, task in enumerate(tasks))
            report = self._execute(assignments, worker)
            if report.status != "completed":
                return "blocked", "研究未完成；暂停后续调查和写入。"
            claims = tuple(claim for result in report.results
                           for claim in worker.claims.get(result.attempt_id, ()))
            review = self.aggregator.aggregate(report.results, claims, required_topics=topics,
                                               investigation_round=round_number)
            self.reviews.append(review.as_dict())
            if review.status == "accepted":
                if writable:
                    coder = self._assignment(
                        goal, f"{goal.goal_id}:code", goal.objective, "edit",
                        dependencies=tuple(item.assignment_id for item in assignments),
                        context=(json.dumps(review.as_dict(), ensure_ascii=False),),
                    )
                    written = self._execute((*assignments, coder), worker,
                                            initial_results=report.results,
                                            before_write=review.write_decision)
                    if written.status != "completed":
                        return "blocked", "代码执行受阻或存在待核对的副作用。"
                return "pending_verification", "研究和已授权修改完成，测试与最终验收待执行。"
            if review.status != "investigate":
                return "needs_review", "证据不足或冲突尚未解决，保留结论分歧并暂停写入。"
            # Every affected researcher receives the bounded previous evidence
            # and explicit investigation objective, then produces a new attempt.
            previous_context = (json.dumps({
                "review": review.as_dict(),
                "previous_claims": [{"topic": c.topic, "conclusion": c.conclusion,
                                     "evidence_refs": c.evidence_refs} for c in claims],
                "instructions": [step.objective for step in review.next_steps],
            }, ensure_ascii=False),)
        return "needs_review", "追加调查预算已耗尽。"


def run_multi_agent(goal: Goal, model: StructuredPlanModel, workdir: Path, **options) -> dict:
    """Public entry point; constructing adapters does not start a run."""
    return MultiAgentWorkflow(model, workdir, **options).run(goal)
