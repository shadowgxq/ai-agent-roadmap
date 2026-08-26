"""LangGraph rewrite of the handwritten routing workflow."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from support_agent.models import RouteDecision, RouteName, RoutingState


ROUTER_SYSTEM_PROMPT = """你是任务路由器，只负责判断用户任务的主要意图。
code_generation 表示从需求生成新代码；
code_review 表示只检查现有代码并提出问题；
bug_fix 表示定位并修复已有代码中的问题；
explanation 表示解释概念、代码或技术原理。
当任务同时包含多个动作时，选择最能代表最终交付目标的路线。
不要执行任务。
"""

BRANCH_PROMPTS: dict[RouteName, str] = {
    "code_generation": (
        "你负责根据用户需求生成完整、可运行的代码。"
        "只完成任务要求，不进行代码评审或额外解释。"
    ),
    "code_review": (
        "你是独立代码评审者。检查正确性、边界情况和完整性，"
        "给出具体问题和原因；不要修改或重写代码。"
    ),
    "bug_fix": (
        "你负责定位并修复用户提供的代码问题。"
        "保留正确行为，只输出修复后的完整代码。"
    ),
    "explanation": (
        "你负责清晰、准确地解释代码和技术概念。"
        "围绕用户问题回答，不生成无关实现。"
    ),
}


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def create_routing_graph(model: BaseChatModel):
    """Build the typed route -> selected branch -> finalize workflow."""

    router_model = model.with_structured_output(
        RouteDecision,
        method="function_calling",
    )

    def classify_route(state: RoutingState) -> dict[str, object]:
        decision = router_model.invoke([
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=state["task"]),
        ])
        return {
            "route": decision.route,
            "route_reason": decision.reason,
            "status": "routing",
        }

    def run_branch(
        state: RoutingState,
        route: RouteName,
    ) -> dict[str, object]:
        response = model.invoke([
            SystemMessage(content=BRANCH_PROMPTS[route]),
            HumanMessage(content=state["task"]),
        ])
        output = _message_text(response)

        if route in {"code_generation", "bug_fix"}:
            return {"code": output, "status": "implementing"}
        if route == "code_review":
            return {"summary": output, "status": "reviewing"}
        return {"summary": output, "status": "summarizing"}

    def code_generation(state: RoutingState) -> dict[str, object]:
        return run_branch(state, "code_generation")

    def code_review(state: RoutingState) -> dict[str, object]:
        return run_branch(state, "code_review")

    def bug_fix(state: RoutingState) -> dict[str, object]:
        return run_branch(state, "bug_fix")

    def explanation(state: RoutingState) -> dict[str, object]:
        return run_branch(state, "explanation")

    def select_route(state: RoutingState) -> RouteName:
        return state["route"]

    def finalize(_: RoutingState) -> dict[str, object]:
        return {"status": "completed"}

    builder = StateGraph(RoutingState)
    builder.add_node("classify_route", classify_route)
    builder.add_node("code_generation", code_generation)
    builder.add_node("code_review", code_review)
    builder.add_node("bug_fix", bug_fix)
    builder.add_node("explanation", explanation)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "classify_route")
    builder.add_conditional_edges(
        "classify_route",
        select_route,
        {
            "code_generation": "code_generation",
            "code_review": "code_review",
            "bug_fix": "bug_fix",
            "explanation": "explanation",
        },
    )
    builder.add_edge("code_generation", "finalize")
    builder.add_edge("code_review", "finalize")
    builder.add_edge("bug_fix", "finalize")
    builder.add_edge("explanation", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
