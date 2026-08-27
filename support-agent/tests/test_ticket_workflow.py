from typing import Any

import pytest
from pydantic import ValidationError

from support_agent.graphs import create_ticket_graph
from support_agent.models import TicketWorkflowClassification
from support_agent.ticket_samples import (
    SESSION_02_SAMPLES,
    TicketSample,
    initial_state_for_sample,
)


class StubModel:
    """Small model double that keeps graph tests independent of provider calls."""

    def __init__(self, classification: TicketWorkflowClassification) -> None:
        self.classification = classification
        self.structured_schema: Any = None
        self.calls = 0

    def with_structured_output(self, schema: Any, *, method: str) -> "StubModel":
        self.structured_schema = schema
        assert method == "function_calling"
        return self

    def invoke(self, _: object) -> TicketWorkflowClassification:
        self.calls += 1
        return self.classification


def _run(sample: TicketSample) -> tuple[dict[str, Any], list[str], StubModel]:
    needs_clarification = bool(sample.expected_clarification)
    model = StubModel(
        TicketWorkflowClassification(
            category="billing",
            priority="normal",
            needs_clarification=needs_clarification,
            missing_fields=["order_id"] if needs_clarification else [],
            reason="test classification",
        )
    )
    graph = create_ticket_graph(model)
    state = initial_state_for_sample(sample)
    result: dict[str, Any] = dict(state)
    visited_nodes: list[str] = []
    for update in graph.stream(state, stream_mode="updates"):
        for node_name, node_update in update.items():
            visited_nodes.append(node_name)
            result.update(node_update)
    return result, visited_nodes, model


@pytest.mark.parametrize("sample", SESSION_02_SAMPLES)
def test_session_02_samples_follow_expected_branch(sample: TicketSample) -> None:
    result, visited_nodes, model = _run(sample)

    assert model.structured_schema is TicketWorkflowClassification
    assert model.calls == 1
    if sample.expected_clarification:
        assert "build_clarification" in visited_nodes
        assert "response_subgraph" not in visited_nodes
        assert result["status"] == "completed"
        assert result["draft_response"]
    else:
        assert "build_clarification" not in visited_nodes
        assert "response_subgraph" in visited_nodes
        assert result["status"] == "failed"
        assert result["error_code"] == "RESPONSE_SUBGRAPH_NOT_READY"


def test_inconsistent_clarification_result_fails_explicitly() -> None:
    state = initial_state_for_sample(SESSION_02_SAMPLES[0])
    model = StubModel(
        TicketWorkflowClassification(
            category="billing",
            priority="normal",
            needs_clarification=True,
            missing_fields=[],
            reason="inconsistent test result",
        )
    )
    graph = create_ticket_graph(model)

    result = graph.invoke(state)

    assert result["status"] == "failed"
    assert result["error_code"] == "MISSING_CLASSIFICATION"
    assert "build_clarification" not in result


def test_missing_fields_use_canonical_identifiers() -> None:
    with pytest.raises(ValidationError):
        TicketWorkflowClassification(
            category="billing",
            priority="normal",
            needs_clarification=True,
            missing_fields=["订单号"],
            reason="invalid field name",
        )
