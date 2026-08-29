"""W14 ticket workflow graph and node I/O contracts."""

from dataclasses import dataclass
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from support_agent.models import (
    EvidenceRef,
    RiskAssessment,
    TicketAgentState,
    TicketWorkflowClassification,
)
from support_agent.policy_corpus import POLICY_CORPUS


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
        error_codes=("POLICY_NOT_FOUND",),
    ),
    "draft_response": NodeIOContract(
        reads=("normalized_text", "evidence_refs"),
        writes=("draft_response", "status", "error_code", "error_message"),
        calls_model=True,
        error_codes=("MODEL_NOT_CONFIGURED", "POLICY_NOT_FOUND",
                     "DRAFT_GENERATION_FAILED"),
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
        error_codes=("MODEL_NOT_CONFIGURED", "RISK_ASSESSMENT_FAILED"),
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
account_email、affected_feature、reproduction_steps、error_message、request_id、
request_context。
如果 category=other 且用户没有说清楚要咨询或处理的具体事项，必须设置
needs_clarification=true，并将 request_context 放入 missing_fields；公司资料等
明确的 other 咨询不需要因此澄清。明确但超出客服业务范围的问题（例如“请问今天
上海天气如何”）也属于信息完整的 other，必须设置 needs_clarification=false、
missing_fields=[]，不能为了把请求转回客服范围而要求 request_context。
billing 的退款问题通常需要 order_id 和 refund_reason；非退款账单问题只按其实际需要
的字段判断，不能因为 category 是 billing 就要求 refund_reason。
billing 问题只允许在确实缺少 order_id、refund_reason 或 request_id 时提出补充；
不要因为账单查询是只读操作而要求 account_email、account_id 或其他账户字段。
account 问题通常需要 account_email 或 account_id；如果文本已经给出邮箱或账户标识，
不要再次要求账户标识。technical 问题通常需要 affected_feature、error_message 或
reproduction_steps；如果文本已经清楚提供这些信息，不要因为还可以追问更多细节而标记缺失。
只列出真正阻塞下一步处理的字段，不要猜测字段值，也不要把可选信息列入 missing_fields。
"""

DRAFT_SYSTEM_PROMPT = """你是企业客服回复草稿生成器。
只根据工单内容和提供的政策证据生成中文客服回复，不要编造证据中没有的政策、承诺或处理结果。
回复必须引用至少一个证据的 source_id，格式为 [source_id]，并在回复最后单独一行写“依据：[source_id]”；
如果证据不足，明确说明无法确认，并提出下一步需要补充的信息。只输出给客户看的回复草稿，
不输出分析过程。
"""

RISK_SYSTEM_PROMPT = """你是企业客服风险评估器。
只返回 risk_level、risk_reasons 和 requires_approval。
low 表示只读咨询或普通信息答复；medium 表示需要人工关注；high 表示可能产生退款、账户变更、
删除数据或其他不可逆副作用。不要因为回复草稿语气平稳就降低用户请求本身的风险等级。
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
    "request_context": "请说明具体要咨询或处理的事项。",
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
        if result.category == "other":
            return {
                "category": result.category,
                "priority": result.priority,
                "missing_fields": ["request_context"],
                "status": "classified",
            }
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


def retrieve_policy_stub(state: TicketAgentState) -> dict[str, object]:
    """Return small, deterministic evidence references for the classified category."""

    category = state.get("category")
    evidence = POLICY_CORPUS.get(category) if category is not None else None
    if evidence is None:
        return {
            "status": "failed",
            "error_code": "POLICY_NOT_FOUND",
            "error_message": f"没有找到 category={category!r} 的政策证据。",
        }
    return {
        "evidence_refs": [ref.model_copy(deep=True) for ref in evidence],
        "status": "retrieving",
    }


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _evidence_payload(evidence_refs: list[EvidenceRef]) -> str:
    return json.dumps(
        [ref.model_dump() for ref in evidence_refs],
        ensure_ascii=False,
    )


def draft_response(
    state: TicketAgentState,
    *,
    model: BaseChatModel | None,
) -> dict[str, object]:
    """Generate an evidence-grounded draft and require a source citation."""

    if model is None:
        return {
            "status": "failed",
            "error_code": "MODEL_NOT_CONFIGURED",
            "error_message": "draft_response 需要注入模型 client。",
        }

    evidence_refs = state.get("evidence_refs", [])
    if not evidence_refs:
        return {
            "status": "failed",
            "error_code": "POLICY_NOT_FOUND",
            "error_message": "draft_response 没有收到政策证据。",
        }

    prompt = (
        f"工单内容：\n{state['normalized_text']}\n\n"
        f"政策证据（只允许使用这些内容）：\n{_evidence_payload(evidence_refs)}\n\n"
        "可用引用 ID："
        + ", ".join(f"[{ref.source_id}]" for ref in evidence_refs)
        + "\n请至少选择一个可用引用 ID，并严格写入回复最后一行。"
    )
    try:
        response = model.invoke([
            SystemMessage(content=DRAFT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
    except Exception as exc:  # noqa: BLE001 - convert provider failure to workflow state.
        return {
            "status": "failed",
            "error_code": "DRAFT_GENERATION_FAILED",
            "error_message": f"draft_response 模型调用失败：{type(exc).__name__}: {exc}",
        }

    draft = _message_text(response)
    if not draft:
        return {
            "status": "failed",
            "error_code": "DRAFT_GENERATION_FAILED",
            "error_message": "draft_response 返回了空内容。",
        }
    if not any(ref.source_id in draft for ref in evidence_refs):
        return {
            "status": "failed",
            "error_code": "DRAFT_GENERATION_FAILED",
            "error_message": "回复草稿没有引用任何政策 source_id。",
        }
    return {
        "draft_response": draft,
        "status": "drafted",
    }


RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _hard_risk_assessment(text: str) -> RiskAssessment:
    """Detect explicit side-effect requests before consulting the model."""

    reasons: list[str] = []
    if "退款" in text and ("代我" in text or "直接" in text or "帮我完成" in text):
        reasons.append("用户明确要求代为执行退款，可能产生资金副作用。")
    if any(
        phrase in text
        for phrase in (
            "帮我修改账户",
            "请直接修改账户",
            "代我修改账户",
            "帮我删除数据",
            "请直接删除数据",
            "代我删除数据",
            "帮我删除账户",
            "请直接删除账户",
        )
    ):
        reasons.append("用户明确要求修改或删除账户数据，可能产生不可逆副作用。")
    if reasons:
        return RiskAssessment(
            risk_level="high",
            risk_reasons=reasons,
            requires_approval=True,
        )
    return RiskAssessment(
        risk_level="low",
        risk_reasons=[],
        requires_approval=False,
    )


def assess_risk(
    state: TicketAgentState,
    *,
    assessor=None,
) -> dict[str, object]:
    """Merge hard-rule risk with semantic model risk without allowing downgrade."""

    hard_result = _hard_risk_assessment(state["normalized_text"])
    if assessor is None:
        return {
            "risk_level": hard_result.risk_level,
            "risk_reasons": hard_result.risk_reasons,
            "requires_approval": hard_result.requires_approval,
            "status": "failed",
            "error_code": "MODEL_NOT_CONFIGURED",
            "error_message": "assess_risk 需要注入结构化风险模型。",
        }

    prompt = (
        f"工单内容：\n{state['normalized_text']}\n\n"
        f"回复草稿：\n{state.get('draft_response', '')}\n\n"
        "请评估语义风险。硬规则结果由代码合并，不能降低其风险等级。"
    )
    try:
        model_result = assessor.invoke([
            SystemMessage(content=RISK_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
    except Exception as exc:  # noqa: BLE001 - convert provider failure to workflow state.
        return {
            "risk_level": hard_result.risk_level,
            "risk_reasons": hard_result.risk_reasons,
            "requires_approval": hard_result.requires_approval,
            "status": "failed",
            "error_code": "RISK_ASSESSMENT_FAILED",
            "error_message": f"assess_risk 模型调用失败：{type(exc).__name__}: {exc}",
        }

    final_level = (
        hard_result.risk_level
        if RISK_RANK[hard_result.risk_level] >= RISK_RANK[model_result.risk_level]
        else model_result.risk_level
    )
    reasons = list(dict.fromkeys(
        hard_result.risk_reasons + model_result.risk_reasons))
    return {
        "risk_level": final_level,
        "risk_reasons": reasons,
        "requires_approval": (
            final_level == "high"
            or hard_result.requires_approval
            or model_result.requires_approval
        ),
        "status": "assessed",
    }


def _route_response(state: TicketAgentState) -> str:
    return "failed" if state["status"] == "failed" else "continue"


def _build_risk_assessor(model: BaseChatModel | None):
    if model is None:
        return None
    return model.with_structured_output(
        RiskAssessment,
        method="function_calling",
    )


def create_response_subgraph(model: BaseChatModel | None = None):
    """Build the policy-grounded response and risk subgraph."""

    risk_assessor = _build_risk_assessor(model)

    def draft_node(state: TicketAgentState) -> dict[str, object]:
        return draft_response(state, model=model)

    def assess_node(state: TicketAgentState) -> dict[str, object]:
        return assess_risk(state, assessor=risk_assessor)

    builder = StateGraph(TicketAgentState)
    builder.add_node("retrieve_policy_stub", retrieve_policy_stub)
    builder.add_node("draft_response", draft_node)
    builder.add_node("assess_risk", assess_node)
    builder.add_edge(START, "retrieve_policy_stub")
    builder.add_conditional_edges(
        "retrieve_policy_stub",
        _route_response,
        {
            "failed": END,
            "continue": "draft_response",
        },
    )
    builder.add_conditional_edges(
        "draft_response",
        _route_response,
        {
            "failed": END,
            "continue": "assess_risk",
        },
    )
    builder.add_edge("assess_risk", END)
    return builder.compile()


def finalize_ticket(state: TicketAgentState) -> dict[str, object]:
    """Set the workflow terminal status while preserving failures."""

    if state["status"] == "failed":
        return {"status": "failed"}
    return {"status": "completed"}


def create_ticket_graph(
    model: BaseChatModel | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Build the ticket graph with optional model and persistence resources."""

    classifier = _build_classifier(model)
    response_subgraph = create_response_subgraph(model)

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

    return builder.compile(checkpointer=checkpointer)
