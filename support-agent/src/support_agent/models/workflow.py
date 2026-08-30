"""Typed contracts for the W14-W15 ticket workflow."""

from typing import Literal, NotRequired, Self, TypedDict

from pydantic import BaseModel, Field, model_validator


TicketCategory = Literal[
    "billing",
    "account",
    "product",
    "technical",
    "other",
]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketMissingField = Literal[
    "order_id",
    "refund_reason",
    "account_id",
    "account_email",
    "affected_feature",
    "reproduction_steps",
    "error_message",
    "request_id",
    "request_context",
]
RiskLevel = Literal["low", "medium", "high"]
ApprovalDecision = Literal["approve", "reject", "revise"]
TicketStatus = Literal[
    "pending",
    "normalized",
    "classified",
    "needs_clarification",
    "retrieving",
    "drafted",
    "assessed",
    "approved",
    "rejected",
    "revising",
    "completed",
    "failed",
]
TicketErrorCode = Literal[
    "INVALID_TICKET",
    "MISSING_CLASSIFICATION",
    "MODEL_NOT_CONFIGURED",
    "POLICY_NOT_FOUND",
    "DRAFT_GENERATION_FAILED",
    "RISK_ASSESSMENT_FAILED",
    "RESPONSE_SUBGRAPH_NOT_READY",
    "INVALID_APPROVAL_DECISION",
    "REVISION_LIMIT_REACHED",
]


class EvidenceRef(BaseModel):
    """Small, serializable reference to policy evidence."""

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    snippet: str = Field(min_length=1)


class TicketAgentState(TypedDict):
    """Serializable business state shared by the W14 ticket graph."""

    # identity
    organization_id: str
    user_id: str
    ticket_id: str
    run_id: str
    thread_id: str

    # input
    subject: str
    description: str
    customer_tier: str

    # control
    status: TicketStatus
    error_code: NotRequired[TicketErrorCode]
    error_message: NotRequired[str]

    # understanding
    normalized_text: NotRequired[str]
    category: NotRequired[TicketCategory]
    priority: NotRequired[TicketPriority]
    missing_fields: NotRequired[list[TicketMissingField]]

    # evidence
    evidence_refs: NotRequired[list[EvidenceRef]]

    # output
    draft_response: NotRequired[str]
    risk_level: NotRequired[RiskLevel]
    risk_reasons: NotRequired[list[str]]
    requires_approval: NotRequired[bool]

    # human approval control state; durable business records arrive in Session 3
    approval_decision: NotRequired[ApprovalDecision]
    approval_feedback: NotRequired[str | None]
    revision_count: NotRequired[int]


class ApprovalResume(BaseModel):
    """Validated human decision supplied through Command(resume=...)."""

    decision: ApprovalDecision
    feedback: str | None = None

    @model_validator(mode="after")
    def require_feedback_for_reject_or_revise(self) -> Self:
        if self.decision in {"reject", "revise"}:
            feedback = self.feedback.strip() if self.feedback else ""
            if not feedback:
                raise ValueError("reject 或 revise 必须提供 feedback。")
            self.feedback = feedback
        return self


class RiskAssessment(BaseModel):
    """Validated semantic risk result for a ticket response."""

    risk_level: RiskLevel
    risk_reasons: list[str] = Field(default_factory=list)
    requires_approval: bool


class TicketWorkflowClassification(BaseModel):
    """Validated classification result for the W14 workflow."""

    category: TicketCategory = Field(description="工单所属业务类别")
    priority: TicketPriority = Field(description="工单处理优先级")
    needs_clarification: bool = Field(description="是否需要补充信息")
    missing_fields: list[TicketMissingField] = Field(
        default_factory=list,
        description=(
            "继续处理所需但当前缺失的 canonical 字段名，"
            "只能使用 order_id、refund_reason、account_id、account_email、"
            "affected_feature、reproduction_steps、error_message、request_id、"
            "request_context"
        ),
    )
    reason: str = Field(min_length=1, description="分类判断依据")
