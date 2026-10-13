"""Frozen case/knowledge snapshots and isolated identities for each execution."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


EVAL_ROOT = Path(__file__).resolve().parents[3] / "evals"
GROUP_COUNTS = {"classification": 8, "retrieval": 8, "low_risk": 5, "approval": 4, "recovery": 3, "security": 2}


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = None
    graph_status: str
    documents: list[str] = Field(default_factory=list)
    writes: int = Field(ge=0, le=1)
    approval_required: bool = False


class E2ECase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    group: Literal["classification", "retrieval", "low_risk", "approval", "recovery", "security"]
    subject: str
    description: str
    decisions: list[Literal["approve", "reject", "revise"]] = Field(default_factory=list)
    scenario: Literal["standard", "replay", "timeout", "cancel", "cross_tenant", "injection"] = "standard"
    expected: Expected
    evidence: str
    failure_categories: list[str]


def load_catalog(root: Path = EVAL_ROOT) -> tuple[dict, list[E2ECase], list[dict]]:
    manifest = json.loads((root / "w21_manifest.json").read_text())
    for filename, digest in manifest["snapshots"].items():
        if sha256((root / filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen snapshot changed: {filename}")
    cases = [E2ECase.model_validate(row) for row in json.loads((root / "w21_cases.json").read_text())]
    if len({case.id for case in cases}) != 30 or Counter(case.group for case in cases) != GROUP_COUNTS:
        raise ValueError("W21 requires 30 unique cases with the frozen group distribution")
    return manifest, cases, json.loads((root / "w21_corpus.json").read_text())


def isolated_ids(case: E2ECase, batch_id: str) -> dict[str, str]:
    return {"organization_id": f"eval-{batch_id}-{case.id}", "user_id": "eval-operator",
            "ticket_id": str(uuid4()), "run_id": str(uuid4()), "thread_id": str(uuid4())}
