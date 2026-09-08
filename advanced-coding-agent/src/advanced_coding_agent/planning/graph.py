"""LangGraph orchestration for the W16 Planning Agent."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..classification import classify_task
from ..contracts import TaskSpec
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

    goal: str
    workdir: str
    constraints: list[str]
    available_tools: list[str]
    classification: dict[str, object]
    planner_result: dict[str, object]
    plan: dict[str, object]
    current_step: str | None
    step_results: list[dict[str, object]]
    execution_status: str
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
) -> PlanningGraphState:
    """Build the serializable input state for one graph thread."""

    return {
        "goal": goal,
        "workdir": str(Path(workdir).resolve()),
        "constraints": list(constraints),
        "available_tools": list(available_tools),
        "graph_status": "pending",
        "execution_status": "pending",
        "replan_count": 0,
        "replan_history": [],
        "tool_call_count": 0,
        "runtime_seconds": 0.0,
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
    ) -> None:
        self.planner = planner
        self.workdir = Path(workdir).resolve()
        self.checkpointer = checkpointer
        self.step_runner = step_runner or self._default_step_runner
        self.verifier = verifier or self._default_verifier
        self.replan_observer = replan_observer
        self.budget = budget or ReplanBudget(max_steps=8)

    def classify(self, state: PlanningGraphState) -> dict[str, object]:
        classification = classify_task(state["goal"])
        return {
            "classification": classification.as_dict(),
            "graph_status": "classified",
        }

    @staticmethod
    def route_after_classify(state: PlanningGraphState) -> Literal[
        "planning", "reactive"
    ]:
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
        return {
            "reactive_result": result.as_dict(),
            "execution_status": result.status,
            "graph_status": "completed" if result.status == "completed" else "blocked",
        }

    def planner(self, state: PlanningGraphState) -> dict[str, object]:
        request = PlanningRequest(
            goal=state["goal"],
            constraints=tuple(state.get("constraints", [])),
            available_tools=tuple(state.get("available_tools", [])),
        )
        result = self.planner.plan(request)
        if result.plan is None:
            return {
                "planner_result": result.as_dict(),
                "graph_status": "completed",
            }

        domain_state = PlanExecutionState.create(result.plan)
        snapshot = domain_state.as_dict()
        return {
            "planner_result": result.as_dict(),
            "plan": snapshot["plan"],
            "current_step": snapshot["current_step"],
            "step_results": snapshot["step_results"],
            "execution_status": snapshot["status"],
            "graph_status": "planned",
            "budget": self.budget.as_dict(),
        }

    def select_step(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        domain_state.claim_next_step()
        updates = self._domain_updates(domain_state)
        updates["graph_status"] = "selected"
        return updates

    @staticmethod
    def route_after_select(state: PlanningGraphState) -> Literal[
        "execute", "done", "blocked"
    ]:
        execution_status = state.get("execution_status")
        if execution_status == "completed":
            return "done"
        if execution_status == "failed":
            return "blocked"
        return "execute"

    def execute(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        step = self._current_step(domain_state)
        try:
            execution = self.step_runner(step, domain_state)
        except Exception as exc:  # noqa: BLE001 - persist execution failure.
            return {
                "last_execution": {
                    "status": "failed",
                    "summary": f"步骤执行失败：{type(exc).__name__}: {exc}",
                    "evidence_refs": [f"runner-error:{step.id}"],
                },
                "graph_status": "executed",
            }
        return {
            "last_execution": {
                "status": "completed",
                "summary": execution.summary,
                "evidence_refs": list(execution.evidence_refs),
            },
            "graph_status": "executed",
        }

    def verify(self, state: PlanningGraphState) -> dict[str, object]:
        domain_state = self._restore_domain_state(state)
        step = self._current_step(domain_state)
        raw_execution = state.get("last_execution")
        if not isinstance(raw_execution, Mapping):
            raise PlanningGraphError("verify 节点缺少 last_execution。")

        execution = StepExecution(
            summary=str(raw_execution.get("summary", "步骤没有执行摘要。")),
            evidence_refs=tuple(
                value
                for value in raw_execution.get("evidence_refs", [])
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
        domain_state.record_step_result(
            step.id,
            status=step_status,
            summary=summary,
            evidence_refs=evidence_refs,
            verification_status=verification.status,
            verification_summary=verification.summary,
        )
        updates = self._domain_updates(domain_state)
        updates["last_verification"] = verification.as_dict()
        updates["graph_status"] = "verified"
        updates["plan_invalidated"] = False
        updates["replan_observation"] = None

        if self.replan_observer is not None:
            observation = self.replan_observer(step, execution, verification)
            if observation is not None:
                updates["plan_invalidated"] = observation.plan_invalidated
                updates["replan_observation"] = observation.as_dict()
        return updates

    @staticmethod
    def route_after_verify(state: PlanningGraphState) -> Literal[
        "next", "replan", "done", "blocked"
    ]:
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
            return {
                "graph_status": "blocked",
                "error": "缺少 evidence-backed replan observation。",
            }

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
            return {
                "graph_status": "blocked",
                "error": result.reason,
                "replan_count": result.replan_count,
            }

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
        return {
            "plan": result.plan.as_dict(),
            "current_step": None,
            "step_results": carried_results,
            "execution_status": "pending",
            "graph_status": "replanned",
            "replan_count": result.replan_count,
            "replan_history": history,
            "tool_call_count": replan_state.tool_call_count,
            "runtime_seconds": replan_state.runtime_seconds,
            "plan_invalidated": False,
            "replan_observation": None,
        }

    @staticmethod
    def route_after_replan(state: PlanningGraphState) -> Literal["next", "blocked"]:
        return "next" if state.get("graph_status") == "replanned" else "blocked"

    @staticmethod
    def blocked(state: PlanningGraphState) -> dict[str, object]:
        return {"graph_status": "blocked"}

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
        }

    @staticmethod
    def _current_step(domain_state: PlanExecutionState) -> PlanStep:
        if domain_state.current_step is None:
            raise PlanningGraphError("当前没有可执行步骤。")
        for step in domain_state.plan.steps:
            if step.id == domain_state.current_step:
                return step
        raise PlanningGraphError(
            f"当前步骤不存在：{domain_state.current_step}。"
        )

    def _budget_from_state(self, state: PlanningGraphState) -> ReplanBudget:
        raw_budget = state.get("budget")
        if not isinstance(raw_budget, Mapping):
            return self.budget
        return ReplanBudget(
            max_replans=int(raw_budget.get("max_replans", self.budget.max_replans)),
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
            runtime_seconds_delta=float(payload.get("runtime_seconds_delta", 0.0)),
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
):
    """Compile the full classify -> plan -> execute -> verify graph."""

    runtime = _PlanningGraphRuntime(
        planner=planner,
        workdir=workdir,
        checkpointer=(
            checkpointer if checkpointer is not None else InMemorySaver()
        ),
        step_runner=step_runner,
        verifier=verifier,
        replan_observer=replan_observer,
        budget=budget,
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
    thread_id: str | None = None,
) -> PlanningGraphState:
    """Invoke one graph thread and persist every node transition."""

    config = {
        "configurable": {"thread_id": thread_id or uuid4().hex}
    }
    return graph.invoke(
        initial_planning_state(
            goal=goal,
            workdir=workdir,
            constraints=constraints,
            available_tools=available_tools,
        ),
        config=config,
    )
