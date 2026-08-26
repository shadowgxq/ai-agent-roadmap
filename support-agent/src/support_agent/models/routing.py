"""Typed contracts for the LangGraph routing workflow."""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field


RouteName = Literal[
    "code_generation",
    "code_review",
    "bug_fix",
    "explanation",
]
RoutingStatus = Literal[
    "pending",
    "routing",
    "implementing",
    "reviewing",
    "summarizing",
    "completed",
]


class RouteDecision(BaseModel):
    """Structured decision produced by the router model."""

    route: RouteName
    reason: str = Field(min_length=1)


class RoutingState(TypedDict):
    """Serializable business state shared by routing graph nodes."""

    task: str
    status: RoutingStatus
    route: NotRequired[RouteName]
    route_reason: NotRequired[str]
    code: NotRequired[str]
    summary: NotRequired[str]
