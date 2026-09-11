"""LangGraph orchestration for the W16 Planning and W17 Goal layers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..classification import classify_task
from ..contracts import TaskSpec
from ..long_horizon import (
    ContextBudget,
    ContextManager,
    ContextSummarizer,
    Goal,
    GoalRunProjection,
    GoalRunStatus,
    ProgressSnapshot,
    SuccessCriterion,
    utc_now_iso,
)
from ..runtime import ReactiveBaseline
from ..verification import VerificationResult
from .execution import (
    PlanExecutionState,
    StepExecution,
    StepRunner,
    StepVerifier,
)
from .plan import AgentPlan, PlanStep
from .planner import Planner, PlanningRequest
from .replan import (
    ReplanBudget,
    ReplanController,
    ReplanObservation,
    ReplanState,
)

LOGGER = logging.getLogger(__name__)

GraphStatus = Literal[
    "pending",
    "classified",
    "planning",
    "planned",
    "selecting",
    "selected",
    "executed",
    "verified",
    "replanned",
    "reactive",
    "completed",
    "blocked",
]


class PlanningGraphState(TypedDict, total=False):
    """Serializable state shared by every LangGraph Planning node."""

    # ``goal`` remains as the W16 objective string for backwards compatibility.
    goal: str
    goal_contract: dict[str, object]
    goal_id: str
    goal_version: int
    run_id: str
    run_projection: dict[str, object]
    workdir: str
    constraints: list[str]
    available_tools: list[str]
    classification: dict[str, object]
    planner_result: dict[str, object]
    plan: dict[str, object]
    current_step: str | None
    step_results: list[dict[str, object]]
    execution_status: str
    blocked_reason: str | None
    progress_snapshot: dict[str, object]
    context_snapshot: dict[str, object]
    graph_status: GraphStatus
    last_execution: dict[str, object]
    last_verification: dict[str, object]
    plan_invalidated: bool
    replan_observation: dict[str, object] | None
    replan_count: int
    replan_history: list[dict[str, object]]
    tool_call_count: int
    runtime_seconds: float
    budget: dict[str, object]
    reactive_result: dict[str, object]
    error: str


ReplanObserver = Callable[
    [PlanStep, StepExecution, VerificationResult],
    ReplanObservation | None,
]


class PlanningGraphError(RuntimeError):
    """Raised when graph state cannot be mapped to domain state safely."""


def initial_planning_state(
    *,
    goal: str,
    workdir: Path,
    constraints: tuple[str, ...] = (),
    available_tools: tuple[str, ...] = (),
    success_criteria: tuple[SuccessCriterion, ...] = (),
    goal_spec: Goal | None = None,
    run_id: str | None = None,
    context_budget: ContextBudget | None = None,
) -> PlanningGraphState:
    """Build serializable input state without copying conversation messages."""

    if goal_spec is None:
        goal_spec = Goal.create(
            objective=goal,
            constraints=constraints,
            success_criteria=success_criteria,
        )
    elif goal.strip() != goal_spec.objective:
        raise PlanningGraphError("goal 与 goal_spec.objective 不一致。")

    resolved_run_id = run_id or uuid4().hex
    projection = GoalRunProjection.from_goal(
        goal_spec,
        run_id=resolved_run_id,
    )
    context_manager = ContextManager.for_goal(
        goal_id=goal_spec.goal_id,
        objective=goal_spec.objective,
        constraints=goal_spec.constraints,
        success_criteria=tuple(
            f"{criterion.id}: {criterion.description}"
            for criterion in goal_spec.success_criteria
        ),
        budget=context_budget,
    )

    return {
        "goal": goal_spec.objective,
        "goal_contract": goal_spec.as_dict(),
        "goal_id": goal_spec.goal_id,
        "goal_version": goal_spec.version,
        "run_id": resolved_run_id,
        "run_projection": projection.as_dict(),
        "workdir": str(Path(workdir).resolve()),
        "constraints": list(goal_spec.constraints),
        "available_tools": list(available_tools),
        "graph_status": "pending",
        "execution_status": "pending",
        "replan_count": 0,
        "replan_history": [],
        "tool_call_count": 0,
        "runtime_seconds": 0.0,
        "progress_snapshot": ProgressSnapshot.empty(
            goal_id=goal_spec.goal_id,
            goal_version=goal_spec.version,
        ).as_dict(),
        "context_snapshot": context_manager.as_dict(),
    }


def _goal_from_state(state: PlanningGraphState) -> Goal:
    """Restore a Goal from state, with a safe fallback for old W16 checkpoints."""

    raw_goal = state.get("goal_contract")
    if isinstance(raw_goal, Mapping):
        return Goal.from_dict(raw_goal)
    return Goal.create(
        objective=state["goal"],
        constraints=tuple(state.get("constraints", [])),
    )


def _projection_updates(
    state: PlanningGraphState,
    *,
    status: GoalRunStatus,
    plan_version: int | None = None,
) -> dict[str, object]:
    """Synchronize the full Goal snapshot and its small query projection."""

    goal_spec = _goal_from_state(state)
    raw_projection = state.get("run_projection")
    if isinstance(raw_projection, Mapping):
        projection = GoalRunProjection.from_dict(raw_projection)
    else:
        projection = GoalRunProjection.from_goal(
            goal_spec,
            run_id=str(state.get("run_id") or uuid4().hex),
        )
    return {
        "goal_contract": goal_spec.as_dict(),
        "goal_id": goal_spec.goal_id,
        "goal_version": goal_spec.version,
        "run_id": projection.run_id,
        "run_projection": projection.with_status(
            status,
            plan_version=plan_version,
        ).as_dict()
    }


class _PlanningGraphRuntime:
    """Bind existing W16 domain components to LangGraph nodes."""

    def __init__(
        self,
        *,
        planner: Planner,
        workdir: Path,
        checkpointer: Any,
        step_runner: StepRunner | None = None,
        verifier: StepVerifier | None = None,
        replan_observer: ReplanObserver | None = None,
        budget: ReplanBudget | None = None,
        context_summarizer: ContextSummarizer | None = None,
    ) -> None:
        self.planner = planner
        self.workdir = Path(workdir).resolve()
        self.checkpointer = checkpointer
        self.step_runner = step_runner or self._default_step_runner
        self.verifier = verifier or self._default_verifier
        self.replan_observer = replan_observer
        self.budget = budget or ReplanBudget(max_steps=8)
        self.context_summarizer = context_summarizer

    def classify(self, state: PlanningGraphState) -> dict[str, object]:
        classification = classify_task(state["goal"])
        updates: dict[str, object] = {
            "classification": classification.as_dict(),
            "graph_status": "classified",
        }
        updates.update(_projection_updates(state, status="running"))
        return updates

    @staticmethod
    def route_after_classify(
        state: PlanningGraphState,
    ) -> Literal["planning", "reactive"]:
        classification = state.get("classification", {})
        return (
            "planning"
            if classification.get("planning_recommended") is True
            else "reactive"
        )

    def reactive(self, state: PlanningGraphState) -> dict[str, object]:
        task = TaskSpec(
            objective=state["goal"],
            workdir=Path(state.get("workdir", str(self.workdir))),
        )
        result = ReactiveBaseline().run(task)
        updates: dict[str, object] = {
            "reactive_result": result.as_dict(),
            "execution_status": result.status,
            "graph_status": "completed" if result.status == "completed" else "blocked",
        }
        updates.update(
            _projection_updates(
                state,
                status="completed" if result.status == "completed" else "blocked",
            )
        )
        return updates

    def planner(self, state: PlanningGraphState) -> dict[str, object]:
        request = PlanningRequest(
            goal=state["goal"],
            constraints=tuple(state.get("constraints", [])),
            available_tools=tuple(state.get("available_tools", [])),
        )
        result = self.planner.plan(request)
        if result.plan is None:
            updates: dict[str, object] = {
                "planner_result": result.as_dict(),
                "graph_status": "completed",
            }
            updates.update(_projection_updates(state, status="completed"))
            return updates

        goal_spec = _goal_from_state(state)
        plan = result.plan.bind_goal(
            goal_id=goal_spec.goal_id,
            goal_version=goal_spec.version,
        )
        domain_state = PlanExecutionState.create(plan)
        snapshot = domain_state.as_dict()
        planner_result = result.as_dict()
        planner_result["plan"] = plan.as_dict()
        context_manager = self._restore_context(state)
        context_manager.add_text(
            item_id=f"plan:{plan.version}",
            layer="permanent",
            content=self._plan_context_content(plan),
            source="plan",
            evidence_refs=(f"plan:{plan.version}",),
        )
        updates = {
            "planner_result": planner_result,
            "plan": snapshot["plan"],
            "current_step": snapshot["current_step"],
            "step_results": snapshot["step_results"],
            "execution_status": snapshot["status"],
            "blocked_reason": snapshot["blocked_reason"],
            "progress_snapshot": domain_state.progress_snapshot(
                remaining_budget=self._remaining_budget(state, domain_state)
            ).as_dict(),
            "context_snapshot": context_manager.as_dict(),
            "graph_status": "planned",
            "budget": self.budget.as_dict(),
        }
        updates.update(
            _projection_updates(
                state,
                status="running",
                plan_version=plan.version,
            )
        )
        return updates

    def select_step(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        domain_state.claim_next_step()
        updates = self._domain_updates(domain_state)
        updates["progress_snapshot"] = domain_state.progress_snapshot(
            remaining_budget=self._remaining_budget(state, domain_state)
        ).as_dict()
        updates["graph_status"] = "selected"
        updates.update(
            _projection_updates(
                state,
                status=(
                    "completed"
                    if domain_state.status == "completed"
                    else "running"
                ),
                plan_version=domain_state.plan.version,
            )
        )
        return updates

    @staticmethod
    def route_after_select(
        state: PlanningGraphState,
    ) -> Literal["execute", "done", "blocked"]:
        execution_status = state.get("execution_status")
        if execution_status == "completed":
            return "done"
        if execution_status == "failed":
            return "blocked"
        if execution_status == "blocked":
            return "blocked"
        return "execute"

    def execute(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        step = self._current_step(domain_state)
        context_manager = self._restore_context(state)
        try:
            execution = self.step_runner(step, domain_state)
        except Exception as exc:  # noqa: BLE001 - persist execution failure.
            error_summary = f"步骤执行失败：{type(exc).__name__}: {exc}"
            context_manager.add_text(
                item_id=f"execution-error:{step.id}",
                layer="compressible",
                content=error_summary,
                source=f"step:{step.id}",
                evidence_refs=(f"runner-error:{step.id}",),
                metadata={"step_id": step.id},
                replace_existing=True,
            )
            self._compact_context(context_manager)
            updates: dict[str, object] = {
                "last_execution": {
                    "step_id": step.id,
                    "status": "failed",
                    "summary": f"步骤执行失败：{type(exc).__name__}: {exc}",
                    "evidence_refs": [f"runner-error:{step.id}"],
                    "tool_call_ids": [],
                },
                "context_snapshot": context_manager.as_dict(),
                "graph_status": "executed",
            }
            updates.update(
                _projection_updates(
                    state,
                    status="running",
                    plan_version=domain_state.plan.version,
                )
            )
            return updates
        updates = {
            "last_execution": {
                "step_id": step.id,
                "status": "completed",
                "summary": execution.summary,
                "evidence_refs": list(execution.evidence_refs),
                "tool_call_ids": list(execution.tool_call_ids),
            },
            "tool_call_count": int(state.get("tool_call_count", 0))
            + len(execution.tool_call_ids),
            "graph_status": "executed",
        }
        self._record_execution_context(context_manager, step, execution)
        self._compact_context(context_manager)
        updates["context_snapshot"] = context_manager.as_dict()
        updates.update(
            _projection_updates(
                state,
                status="running",
                plan_version=domain_state.plan.version,
            )
        )
        return updates

    def verify(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        step = self._current_step(domain_state)
        context_manager = self._restore_context(state)
        raw_execution = state.get("last_execution")
        if not isinstance(raw_execution, Mapping):
            raise PlanningGraphError("verify 节点缺少 last_execution。")
        raw_step_id = raw_execution.get("step_id")
        if raw_step_id is not None and raw_step_id != step.id:
            raise PlanningGraphError(
                f"last_execution 属于步骤 {raw_step_id}，当前步骤是 {step.id}。"
            )

        execution = StepExecution(
            summary=str(raw_execution.get("summary", "步骤没有执行摘要。")),
            evidence_refs=tuple(
                value
                for value in raw_execution.get("evidence_refs", [])
                if isinstance(value, str) and value.strip()
            ),
            tool_call_ids=tuple(
                value
                for value in raw_execution.get("tool_call_ids", [])
                if isinstance(value, str) and value.strip()
            ),
        )
        if raw_execution.get("status") == "failed":
            verification = VerificationResult(
                status="fail",
                summary="步骤执行失败，验证不通过。",
                evidence_refs=(f"execution-failed:{step.id}",),
            )
        else:
            try:
                verification = self.verifier(step, execution)
            except Exception as exc:  # noqa: BLE001 - verifier needs review.
                verification = VerificationResult(
                    status="needs_review",
                    summary=f"验证器执行失败：{type(exc).__name__}。",
                    evidence_refs=(f"verifier-error:{step.id}",),
                )

        evidence_refs = tuple(
            dict.fromkeys(execution.evidence_refs + verification.evidence_refs)
        )
        step_status = "completed" if verification.status == "pass" else "failed"
        summary = (
            execution.summary
            if step_status == "completed"
            else f"{execution.summary}；验证未通过。"
        )
        context_manager.add_text(
            item_id=f"verification:{step.id}",
            layer="compressible",
            content=verification.summary,
            source=f"step:{step.id}:verification",
            evidence_refs=verification.evidence_refs,
            metadata={"step_id": step.id, "status": verification.status},
            replace_existing=True,
        )
        self._compact_context(context_manager)
        domain_state.record_step_result(
            step.id,
            status=step_status,
            summary=summary,
            evidence_refs=evidence_refs,
            verification_status=verification.status,
            verification_summary=verification.summary,
            tool_call_ids=execution.tool_call_ids,
            failure_reason=(
                None
                if step_status == "completed"
                else verification.summary
            ),
        )
        updates = self._domain_updates(domain_state)
        updates["progress_snapshot"] = domain_state.progress_snapshot(
            remaining_budget=self._remaining_budget(state, domain_state)
        ).as_dict()
        updates["context_snapshot"] = context_manager.as_dict()
        updates["last_verification"] = verification.as_dict()
        updates["graph_status"] = "verified"
        updates["plan_invalidated"] = False
        updates["replan_observation"] = None
        updates.update(
            _projection_updates(
                state,
                status=(
                    "completed"
                    if domain_state.status == "completed"
                    else "failed"
                    if domain_state.status == "failed"
                    else "running"
                ),
                plan_version=domain_state.plan.version,
            )
        )

        if self.replan_observer is not None:
            observation = self.replan_observer(step, execution, verification)
            if observation is not None:
                updates["plan_invalidated"] = observation.plan_invalidated
                updates["replan_observation"] = observation.as_dict()
        return updates

    @staticmethod
    def route_after_verify(
        state: PlanningGraphState,
    ) -> Literal["next", "replan", "done", "blocked"]:
        if state.get("execution_status") == "completed":
            return "done"
        if state.get("execution_status") == "pending":
            return "next"
        if state.get("plan_invalidated") and state.get("replan_observation"):
            return "replan"
        return "blocked"

    def replan(self, state: PlanningGraphState) -> dict[str, object]:
        raw_observation = state.get("replan_observation")
        if not isinstance(raw_observation, Mapping):
            reason = "缺少 evidence-backed replan observation。"
            updates: dict[str, object] = {
                "graph_status": "blocked",
                "error": reason,
                "execution_status": "blocked",
                "blocked_reason": reason,
            }
            updates.update(_projection_updates(state, status="blocked"))
            return updates

        current_plan = self._restore_domain_state(state).plan
        observation = self._observation_from_dict(raw_observation)
        budget = self._budget_from_state(state)
        replan_state = ReplanState.create(current_plan, budget)
        replan_state.replan_count = int(state.get("replan_count", 0))
        replan_state.tool_call_count = int(state.get("tool_call_count", 0))
        replan_state.runtime_seconds = float(state.get("runtime_seconds", 0.0))

        result = ReplanController(self.planner).consider(
            replan_state,
            observation,
        )
        if result.decision != "replanned":
            updates = {
                "graph_status": "blocked",
                "error": result.reason,
                "execution_status": "blocked",
                "blocked_reason": result.reason,
                "replan_count": result.replan_count,
            }
            updates.update(_projection_updates(state, status="blocked"))
            return updates

        history = list(state.get("replan_history", []))
        history.append(
            {
                "previous_plan": current_plan.as_dict(),
                "new_plan": result.plan.as_dict(),
                "trigger": observation.as_dict(),
            }
        )
        carried_results = self._carry_results(
            state.get("step_results", []),
            result.plan,
        )
        context_manager = self._restore_context(state)
        previous_plan_item_id = f"plan:{current_plan.version}"
        if previous_plan_item_id in context_manager.items:
            context_manager.deactivate(previous_plan_item_id)
        context_manager.add_text(
            item_id=f"plan:{result.plan.version}",
            layer="permanent",
            content=self._plan_context_content(result.plan),
            source="replan",
            evidence_refs=(f"plan:{result.plan.version}",),
        )
        self._compact_context(context_manager)
        updates = {
            "plan": result.plan.as_dict(),
            "current_step": None,
            "step_results": carried_results,
            "execution_status": "pending",
            "blocked_reason": None,
            "graph_status": "replanned",
            "replan_count": result.replan_count,
            "replan_history": history,
            "tool_call_count": replan_state.tool_call_count,
            "runtime_seconds": replan_state.runtime_seconds,
            "plan_invalidated": False,
            "replan_observation": None,
            "context_snapshot": context_manager.as_dict(),
        }
        replanned_state = PlanExecutionState.from_dict(
            {
                "plan": result.plan.as_dict(),
                "current_step": None,
                "step_results": carried_results,
                "status": "pending",
            }
        )
        updates["progress_snapshot"] = replanned_state.progress_snapshot(
            remaining_budget=self._remaining_budget(state, replanned_state)
        ).as_dict()
        updates.update(
            _projection_updates(
                state,
                status="running",
                plan_version=result.plan.version,
            )
        )
        return updates

    @staticmethod
    def route_after_replan(state: PlanningGraphState) -> Literal["next", "blocked"]:
        return "next" if state.get("graph_status") == "replanned" else "blocked"

    @staticmethod
    def blocked(state: PlanningGraphState) -> dict[str, object]:
        reason = (
            state.get("blocked_reason")
            or state.get("error")
            or "执行状态进入 blocked，等待人工介入。"
        )
        updates: dict[str, object] = {
            "graph_status": "blocked",
            "execution_status": "blocked",
            "blocked_reason": reason,
        }
        raw_snapshot = state.get("progress_snapshot")
        if isinstance(raw_snapshot, Mapping):
            try:
                snapshot = ProgressSnapshot.from_dict(raw_snapshot)
                updates["progress_snapshot"] = replace(
                    snapshot,
                    status="blocked",
                    blocked_reason=reason,
                    updated_at=utc_now_iso(),
                ).as_dict()
            except Exception:
                LOGGER.debug(
                    "无法将无效 progress snapshot 标记为 blocked，保留原状态。",
                    exc_info=True,
                )
        updates.update(_projection_updates(state, status="blocked"))
        return updates

    def _restore_domain_state(
        self,
        state: PlanningGraphState,
    ) -> PlanExecutionState:
        raw_plan = state.get("plan")
        if not isinstance(raw_plan, Mapping):
            raise PlanningGraphError("graph state 缺少结构化 plan。")
        raw_results = state.get("step_results", [])
        if not isinstance(raw_results, list):
            raise PlanningGraphError("graph state 的 step_results 必须是数组。")
        return PlanExecutionState.from_dict(
            {
                "plan": raw_plan,
                "current_step": state.get("current_step"),
                "step_results": raw_results,
                "status": state.get("execution_status", "pending"),
                "blocked_reason": state.get("blocked_reason"),
            }
        )

    @staticmethod
    def _domain_updates(domain_state: PlanExecutionState) -> dict[str, object]:
        snapshot = domain_state.as_dict()
        return {
            "plan": snapshot["plan"],
            "current_step": snapshot["current_step"],
            "step_results": snapshot["step_results"],
            "execution_status": snapshot["status"],
            "blocked_reason": snapshot["blocked_reason"],
            "progress_snapshot": snapshot["progress_snapshot"],
        }

    def _restore_context(self, state: PlanningGraphState) -> ContextManager:
        raw_context = state.get("context_snapshot")
        if isinstance(raw_context, Mapping):
            return ContextManager.from_dict(raw_context)
        goal_spec = _goal_from_state(state)
        return ContextManager.for_goal(
            goal_id=goal_spec.goal_id,
            objective=goal_spec.objective,
            constraints=goal_spec.constraints,
            success_criteria=tuple(
                f"{criterion.id}: {criterion.description}"
                for criterion in goal_spec.success_criteria
            ),
        )

    @staticmethod
    def _plan_context_content(plan: AgentPlan) -> str:
        steps = "\n".join(
            f"- {step.id}: {step.description}"
            for step in plan.steps
        )
        return f"Plan v{plan.version} for {plan.goal}\n{steps}"

    @staticmethod
    def _record_execution_context(
        context: ContextManager,
        step: PlanStep,
        execution: StepExecution,
    ) -> None:
        if execution.tool_call_ids:
            for tool_call_id in execution.tool_call_ids:
                context.record_tool_result(
                    step_id=step.id,
                    tool_call_id=tool_call_id,
                    summary=execution.summary,
                    evidence_refs=execution.evidence_refs,
                )
            return
        context.add_text(
            item_id=f"execution:{step.id}",
            layer="compressible",
            content=execution.summary,
            source=f"step:{step.id}",
            evidence_refs=execution.evidence_refs,
            metadata={"step_id": step.id},
            replace_existing=True,
        )

    def _compact_context(self, context: ContextManager) -> None:
        """Compact with the injected LLM and retain a deterministic fallback."""

        if self.context_summarizer is None:
            context.compact_if_needed()
            return
        try:
            context.compact_if_needed(summarizer=self.context_summarizer)
        except Exception as exc:  # noqa: BLE001 - fallback keeps the run resumable.
            context.compact_if_needed(
                information_loss_feedback=(
                    "LLM context summarizer failed; deterministic fallback "
                    f"used ({type(exc).__name__})."
                )
            )

    def _remaining_budget(
        self,
        state: PlanningGraphState,
        domain_state: PlanExecutionState,
    ) -> dict[str, object]:
        """Expose budget headroom without leaking the full runtime state."""

        budget = self._budget_from_state(state)
        return {
            "replans": max(
                0,
                budget.max_replans - int(state.get("replan_count", 0)),
            ),
            "steps": max(
                0,
                budget.max_steps - len(domain_state.completed_step_ids),
            ),
            "tool_calls": max(
                0,
                budget.max_tool_calls - int(state.get("tool_call_count", 0)),
            ),
            "runtime_seconds": max(
                0.0,
                budget.max_runtime_seconds
                - float(state.get("runtime_seconds", 0.0)),
            ),
        }

    @staticmethod
    def _current_step(domain_state: PlanExecutionState) -> PlanStep:
        if domain_state.current_step is None:
            raise PlanningGraphError("当前没有可执行步骤。")
        for step in domain_state.plan.steps:
            if step.id == domain_state.current_step:
                return step
        raise PlanningGraphError(f"当前步骤不存在：{domain_state.current_step}。")

    def _budget_from_state(self, state: PlanningGraphState) -> ReplanBudget:
        raw_budget = state.get("budget")
        if not isinstance(raw_budget, Mapping):
            return self.budget
        return ReplanBudget(
            max_replans=int(raw_budget.get(
                "max_replans", self.budget.max_replans)),
            max_steps=int(raw_budget.get("max_steps", self.budget.max_steps)),
            max_tool_calls=int(
                raw_budget.get("max_tool_calls", self.budget.max_tool_calls)
            ),
            max_runtime_seconds=float(
                raw_budget.get(
                    "max_runtime_seconds",
                    self.budget.max_runtime_seconds,
                )
            ),
        )

    @staticmethod
    def _observation_from_dict(
        payload: Mapping[str, object],
    ) -> ReplanObservation:
        evidence_refs = payload.get("evidence_refs", [])
        affected_step_ids = payload.get("affected_step_ids", [])
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise PlanningGraphError("replan observation 缺少 evidence_refs。")
        if not isinstance(affected_step_ids, list):
            raise PlanningGraphError("affected_step_ids 必须是数组。")
        return ReplanObservation(
            summary=str(payload.get("summary", "")),
            plan_invalidated=bool(payload.get("plan_invalidated", False)),
            evidence_refs=tuple(str(value) for value in evidence_refs),
            affected_step_ids=tuple(str(value) for value in affected_step_ids),
            tool_calls_delta=int(payload.get("tool_calls_delta", 0)),
            runtime_seconds_delta=float(
                payload.get("runtime_seconds_delta", 0.0)),
        )

    @staticmethod
    def _carry_results(
        raw_results: object,
        plan: AgentPlan,
    ) -> list[dict[str, object]]:
        if not isinstance(raw_results, list):
            return []
        known_ids = {step.id for step in plan.steps}
        return [
            result
            for result in raw_results
            if isinstance(result, dict)
            and result.get("step_id") in known_ids
            and result.get("status") == "completed"
        ]

    @staticmethod
    def _default_step_runner(
        step: PlanStep,
        _state: PlanExecutionState,
    ) -> StepExecution:
        return StepExecution(
            summary=f"演示执行：{step.description}",
            evidence_refs=(f"step-result:{step.id}",),
        )

    @staticmethod
    def _default_verifier(
        step: PlanStep,
        _execution: StepExecution,
    ) -> VerificationResult:
        return VerificationResult(
            status="pass",
            summary=f"演示验证通过：{step.id}。",
            evidence_refs=(f"verification:{step.id}",),
        )


def create_planning_graph(
    *,
    planner: Planner,
    workdir: Path,
    checkpointer: Any | None = None,
    step_runner: StepRunner | None = None,
    verifier: StepVerifier | None = None,
    replan_observer: ReplanObserver | None = None,
    budget: ReplanBudget | None = None,
    context_summarizer: ContextSummarizer | None = None,
):
    """Compile the graph and optionally inject an LLM context summarizer."""

    runtime = _PlanningGraphRuntime(
        planner=planner,
        workdir=workdir,
        checkpointer=(
            checkpointer if checkpointer is not None else InMemorySaver()),
        step_runner=step_runner,
        verifier=verifier,
        replan_observer=replan_observer,
        budget=budget,
        context_summarizer=context_summarizer,
    )
    builder = StateGraph(PlanningGraphState)
    builder.add_node("classify", runtime.classify)
    builder.add_node("reactive", runtime.reactive)
    builder.add_node("planner", runtime.planner)
    builder.add_node("select_step", runtime.select_step)
    builder.add_node("execute", runtime.execute)
    builder.add_node("verify", runtime.verify)
    builder.add_node("replan", runtime.replan)
    builder.add_node("blocked", runtime.blocked)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        runtime.route_after_classify,
        {"reactive": "reactive", "planning": "planner"},
    )
    builder.add_edge("reactive", END)
    builder.add_edge("planner", "select_step")
    builder.add_conditional_edges(
        "select_step",
        runtime.route_after_select,
        {"execute": "execute", "done": END, "blocked": "blocked"},
    )
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges(
        "verify",
        runtime.route_after_verify,
        {
            "next": "select_step",
            "replan": "replan",
            "done": END,
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "replan",
        runtime.route_after_replan,
        {"next": "select_step", "blocked": "blocked"},
    )
    builder.add_edge("blocked", END)
    return builder.compile(checkpointer=runtime.checkpointer)


def invoke_planning_graph(
    graph: Any,
    *,
    goal: str,
    workdir: Path,
    constraints: tuple[str, ...] = (),
    available_tools: tuple[str, ...] = (),
    success_criteria: tuple[SuccessCriterion, ...] = (),
    goal_spec: Goal | None = None,
    thread_id: str | None = None,
    context_budget: ContextBudget | None = None,
) -> PlanningGraphState:
    """Invoke one graph thread and persist every node transition."""

    resolved_thread_id = thread_id or uuid4().hex
    config = {"configurable": {"thread_id": resolved_thread_id}}
    return graph.invoke(
        initial_planning_state(
            goal=goal,
            workdir=workdir,
            constraints=constraints,
            available_tools=available_tools,
            success_criteria=success_criteria,
            goal_spec=goal_spec,
            run_id=resolved_thread_id,
            context_budget=context_budget,
        ),
        config=config,
    )
