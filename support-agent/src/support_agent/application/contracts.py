"""Business identity and run transitions; queue state is not business state."""

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


Role = Literal["viewer", "operator", "approver", "admin"]
RunStatus = Literal["queued", "running", "waiting_approval", "succeeded", "failed", "cancelled"]
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"queued", "waiting_approval", "succeeded", "failed", "cancelled"},
    "waiting_approval": {"queued", "cancelled", "failed"},
    "succeeded": set(), "failed": set(), "cancelled": set(),
}


class ConflictError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise ConflictError(f"Illegal run transition: {current} -> {target}")


@dataclass(frozen=True)
class Identity:
    organization_id: str
    user_id: str
    role: Role

    def require(self, *roles: str) -> None:
        if self.role != "admin" and self.role not in roles:
            raise PermissionError("Insufficient permission")


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    knowledge_base_id: str = Field(min_length=1, max_length=100)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "revise"]
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feedback: str | None = Field(default=None, max_length=2000)


def request_hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest()


def validate_key(key: str) -> str:
    if not 1 <= len(key) <= 128 or not key.isascii() or any(ord(c) < 33 for c in key):
        raise ValueError("Idempotency-Key must be 1-128 printable ASCII characters")
    return key
