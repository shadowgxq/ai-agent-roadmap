"""Domain and structured-output models for support-agent."""

from .routing import RouteDecision, RouteName, RoutingState
from .ticket import TicketClassification
from .workflow import (
    EvidenceRef,
    RiskAssessment,
    RiskLevel,
    TicketAgentState,
    TicketCategory,
    TicketErrorCode,
    TicketMissingField,
    TicketPriority,
    TicketStatus,
    TicketWorkflowClassification,
)

__all__ = [
    "RouteDecision",
    "RouteName",
    "RoutingState",
    "TicketClassification",
    "EvidenceRef",
    "RiskAssessment",
    "RiskLevel",
    "TicketAgentState",
    "TicketCategory",
    "TicketErrorCode",
    "TicketMissingField",
    "TicketPriority",
    "TicketStatus",
    "TicketWorkflowClassification",
]
