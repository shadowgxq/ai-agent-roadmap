from typing import Any

from langchain_core.messages import AIMessage
import pytest
from pydantic import ValidationError

from support_agent.graphs import create_ticket_graph
from support_agent.models import RiskAssessment, TicketWorkflowClassification
from support_agent.ticket_samples import (
    SESSION_02_SAMPLES,
    SESSION_03_RISK_SAMPLES,
    TicketSample,
    initial_state_for_sample,
)


class StubStructuredOutput:
    """Return the configured result for one structured-output schema."""

    def __init__(self, parent: "StubModel", schema: Any) -> None:
        self.parent = parent
        self.schema = schema

    def invoke(self, _: object) -> Any:
        self.parent.structured_calls.append(self.schema)
        if self.schema is TicketWorkflowClassification:
            self.parent.classification_calls += 1
            return self.parent.classification
        if self.schema is RiskAssessment:
            self.parent.risk_calls += 1
            return self.parent.risk_assessment
        raise AssertionError(f"unexpected schema: {self.schema!r}")


class StubModel:
    """Small model double that keeps graph tests independent of provider calls."""

    def __init__(
        self,
        classification: TicketWorkflowClassification,
        *,
        draft_response: str = "根据政策 [billing_refund_001]，我们会继续核对相关信息。",
        risk_assessment: RiskAssessment | None = None,
    ) -> None:
        self.classification = classification
        self.draft_response = draft_response
        self.risk_assessment = risk_assessment or RiskAssessment(
            risk_level="low",
            risk_reasons=[],
            requires_approval=False,
        )
        self.structured_calls: list[Any] = []
        self.classification_calls = 0
        self.draft_calls = 0
        self.risk_calls = 0

    def with_structured_output(
        self,
        schema: Any,
        *,
        method: str,
    ) -> StubStructuredOutput:
        assert method == "function_calling"
        return StubStructuredOutput(self, schema)

    def invoke(self, _: object) -> AIMessage:
        self.draft_calls += 1
        return AIMessage(content=self.draft_response)


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

    assert TicketWorkflowClassification in model.structured_calls
    assert model.classification_calls == 1
    if sample.expected_clarification:
        assert "build_clarification" in visited_nodes
        assert "response_subgraph" not in visited_nodes
        assert result["status"] == "completed"
        assert result["draft_response"]
        assert model.draft_calls == 0
        assert model.risk_calls == 0
    else:
        assert "build_clarification" not in visited_nodes
        assert "response_subgraph" in visited_nodes
        assert result["status"] == "completed"
        assert result["draft_response"]
        assert result["risk_level"] == "low"
        assert result["requires_approval"] is False
        assert model.draft_calls == 1
        assert model.risk_calls == 1


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


def test_hard_risk_rule_cannot_be_downgraded_by_model() -> None:
    sample = SESSION_03_RISK_SAMPLES[1]
    model = StubModel(
        TicketWorkflowClassification(
            category="billing",
            priority="high",
            needs_clarification=False,
            missing_fields=[],
            reason="complete refund request",
        ),
        risk_assessment=RiskAssessment(
            risk_level="low",
            risk_reasons=["模型误判为普通咨询。"],
            requires_approval=False,
        ),
    )
    graph = create_ticket_graph(model)

    result = graph.invoke(initial_state_for_sample(sample))

    assert result["status"] == "completed"
    assert result["risk_level"] == "high"
    assert result["requires_approval"] is True
    assert "资金副作用" in result["risk_reasons"][0]
