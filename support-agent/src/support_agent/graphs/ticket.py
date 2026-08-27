"""W14 ticket workflow graph and node I/O contracts."""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from support_agent.models import (
    TicketAgentState,
    TicketWorkflowClassification,
)


@dataclass(frozen=True)
class NodeIOContract:
    """Document the state boundary owned by one workflow node."""

    reads: tuple[str, ...]
    writes: tuple[str, ...]
    calls_model: bool
    error_codes: tuple[str, ...] = ()


NODE_IO_CONTRACTS: dict[str, NodeIOContract] = {
    "normalize_ticket": NodeIOContract(
        reads=("subject", "description"),
        writes=("normalized_text", "status", "error_code", "error_message"),
        calls_model=False,
        error_codes=("INVALID_TICKET",),
    ),
    "classify_ticket": NodeIOContract(
        reads=("normalized_text",),
        writes=(
            "category",
            "priority",
            "missing_fields",
            "status",
            "error_code",
            "error_message",
        ),
        calls_model=True,
        error_codes=("MISSING_CLASSIFICATION",),
    ),
    "build_clarification": NodeIOContract(
        reads=("missing_fields",),
        writes=("draft_response", "status"),
        calls_model=False,
    ),
    "retrieve_policy_stub": NodeIOContract(
        reads=("category",),
        writes=("evidence_refs", "status", "error_code", "error_message"),
        calls_model=False,
        error_codes=("RESPONSE_SUBGRAPH_NOT_READY",),
    ),
    "draft_response": NodeIOContract(
        reads=("normalized_text", "evidence_refs"),
        writes=("draft_response", "status", "error_code", "error_message"),
        calls_model=True,
        error_codes=("RESPONSE_SUBGRAPH_NOT_READY",),
    ),
    "assess_risk": NodeIOContract(
        reads=("normalized_text", "draft_response"),
        writes=(
            "risk_level",
            "risk_reasons",
            "requires_approval",
            "status",
            "error_code",
            "error_message",
        ),
        calls_model=True,
        error_codes=("RESPONSE_SUBGRAPH_NOT_READY",),
    ),
    "finalize": NodeIOContract(
        reads=("status", "draft_response", "risk_level"),
        writes=("status",),
        calls_model=False,
    ),
}


CLASSIFICATION_SYSTEM_PROMPT = """你是企业客服工单分类器。
只根据工单内容判断 category、priority 和缺失字段，不生成客服回复。
category 只能是 billing、account、product、technical、other 之一；
priority 只能是 low、normal、high、urgent 之一。
category 判定规则：billing 是账单、扣款、退款；account 是登录、账户资料或账户安全；
product 是产品功能使用、配置或操作入口咨询（例如导出数据）；technical 只用于错误、
异常、接口失败或服务故障；不符合以上类别才使用 other。产品使用问题即使提到某个功能，
也不要误判为 technical，除非用户明确报告错误或失败。
如果继续处理需要但工单没有提供的信息，列入 missing_fields；
needs_clarification 必须等于 missing_fields 是否非空。
missing_fields 只能使用 canonical 字段名：order_id、refund_reason、account_id、
account_email、affected_feature、reproduction_steps、error_message、request_id。
billing 的退款问题通常需要 order_id 和 refund_reason；非退款账单问题只按其实际需要
的字段判断，不能因为 category 是 billing 就要求 refund_reason。
account 问题通常需要 account_email 或 account_id；如果文本已经给出邮箱或账户标识，
不要再次要求账户标识。technical 问题通常需要 affected_feature、error_message 或
reproduction_steps；如果文本已经清楚提供这些信息，不要因为还可以追问更多细节而标记缺失。
只列出真正阻塞下一步处理的字段，不要猜测字段值，也不要把可选信息列入 missing_fields。
"""

CLARIFICATION_QUESTIONS = {
    "order_id": "请提供需要处理的订单号。",
    "refund_reason": "请说明申请退款的原因。",
    "account_id": "请提供受影响的账户标识。",
    "account_email": "请提供账户邮箱。",
    "affected_feature": "请说明受影响的账户功能。",
    "reproduction_steps": "请提供问题的复现步骤。",
    "error_message": "请提供完整的错误信息。",
    "request_id": "请提供请求 ID。",
}


def normalize_ticket(state: TicketAgentState) -> dict[str, object]:
    """Trim and combine ticket input without invoking a model."""

    subject = state["subject"].strip()
    description = state["description"].strip()
    if not subject or not description:
        return {
            "status": "failed",
            "error_code": "INVALID_TICKET",
            "error_message": "subject 和 description 不能为空。",
        }

    return {
        "normalized_text": (
            f"Subject: {subject}\n"
            f"Description: {description}"
        ),
        "status": "normalized",
    }


def _missing_classification() -> dict[str, object]:
    return {
        "status": "failed",
        "error_code": "MISSING_CLASSIFICATION",
        "error_message": (
            "Session 1 的无模型路径需要调用方预先提供 category、"
            "priority 和 missing_fields。"
        ),
    }


def _build_classifier(model: BaseChatModel | None):
    if model is None:
        return None
    return model.with_structured_output(
        TicketWorkflowClassification,
        method="function_calling",
    )


def classify_ticket(
    state: TicketAgentState,
    *,
    classifier=None,
) -> dict[str, object]:
    """Return classification fields; the model is injected by the graph factory."""

    if classifier is None:
        if not all(
            key in state
            for key in ("category", "priority", "missing_fields")
        ):
            return _missing_classification()
        return {"status": "classified"}

    result = classifier.invoke([
        SystemMessage(content=CLASSIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=state["normalized_text"]),
    ])
    if result.needs_clarification and not result.missing_fields:
        return {
            "status": "failed",
            "error_code": "MISSING_CLASSIFICATION",
            "error_message": (
                "分类结果声明需要澄清，但没有提供 missing_fields，"
                "无法生成精确的澄清问题。"
            ),
        }
    return {
        "category": result.category,
        "priority": result.priority,
        "missing_fields": result.missing_fields,
        "status": "classified",
    }


def route_after_normalize(state: TicketAgentState) -> str:
    """Choose classification or the terminal error path."""

    return "failed" if state["status"] == "failed" else "classify"


def route_after_classification(state: TicketAgentState) -> str:
    """Choose clarification, response processing, or the terminal error path."""

    if state["status"] == "failed":
        return "failed"
    if state.get("missing_fields"):
        return "clarification"
    return "response"


def build_clarification(state: TicketAgentState) -> dict[str, object]:
    """Create deterministic questions for the fields missing from a ticket."""

    questions = [
        CLARIFICATION_QUESTIONS.get(
            field,
            f"请补充字段：{field}。",
        )
        for field in state.get("missing_fields", [])
    ]
    return {
        "draft_response": "\n".join(questions),
        "status": "needs_clarification",
    }


def _response_not_ready(_: TicketAgentState) -> dict[str, object]:
    """Keep future response nodes explicit without pretending they are implemented."""

    return {
        "status": "failed",
        "error_code": "RESPONSE_SUBGRAPH_NOT_READY",
        "error_message": (
            "retrieve_policy_stub、draft_response 和 assess_risk 将在后续 W14 Session 实现。"
        ),
    }


def _route_response(state: TicketAgentState) -> str:
    return "failed" if state["status"] == "failed" else "continue"


def create_response_subgraph():
    """Build the response subgraph boundary for later W14 sessions."""

    builder = StateGraph(TicketAgentState)
    builder.add_node("retrieve_policy_stub", _response_not_ready)
    builder.add_node("draft_response", _response_not_ready)
    builder.add_node("assess_risk", _response_not_ready)
    builder.add_edge(START, "retrieve_policy_stub")
    builder.add_conditional_edges(
        "retrieve_policy_stub",
        _route_response,
        {
            "failed": END,
            "continue": "draft_response",
        },
    )
    builder.add_edge("draft_response", "assess_risk")
    builder.add_edge("assess_risk", END)
    return builder.compile()


def finalize_ticket(state: TicketAgentState) -> dict[str, object]:
    """Set the workflow terminal status while preserving failures."""

    if state["status"] == "failed":
        return {"status": "failed"}
    return {"status": "completed"}


def create_ticket_graph(model: BaseChatModel | None = None):
    """Build the W14 parent graph with an optional classification model."""

    classifier = _build_classifier(model)
    response_subgraph = create_response_subgraph()

    def classify_node(state: TicketAgentState) -> dict[str, object]:
        return classify_ticket(state, classifier=classifier)

    builder = StateGraph(TicketAgentState)
    builder.add_node("normalize_ticket", normalize_ticket)
    builder.add_node("classify_ticket", classify_node)
    builder.add_node("build_clarification", build_clarification)
    builder.add_node("response_subgraph", response_subgraph)
    builder.add_node("finalize", finalize_ticket)

    builder.add_edge(START, "normalize_ticket")
    builder.add_conditional_edges(
        "normalize_ticket",
        route_after_normalize,
        {
            "classify": "classify_ticket",
            "failed": "finalize",
        },
    )
    builder.add_conditional_edges(
        "classify_ticket",
        route_after_classification,
        {
            "clarification": "build_clarification",
            "response": "response_subgraph",
            "failed": "finalize",
        },
    )
    builder.add_edge("build_clarification", "finalize")
    builder.add_edge("response_subgraph", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
