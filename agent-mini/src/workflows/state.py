from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WorkflowStatus = Literal[
    "pending",
    "routing",
    "parallelizing",
    "voting",
    "planning",
    "implementing",
    "reviewing",
    "summarizing",
    "completed",
    "failed",
]


class WorkflowState(BaseModel):
    """Workflow 在执行过程中的共享状态。"""

    model_config = ConfigDict(validate_assignment=True)

    task: str = Field(min_length=1)
    plan: str = ""
    code: str = ""
    summary: str = ""
    review_feedback: list[str] = Field(default_factory=list)
    iteration: int = Field(default=0, ge=0)
    status: WorkflowStatus = "pending"
