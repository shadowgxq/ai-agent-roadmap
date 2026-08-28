from datetime import datetime, timezone

from support_agent.models import AgentEvent
from support_agent.ticket_acceptance_cli import evaluate_case
from support_agent.ticket_samples import SESSION_05_SAMPLES


def _event(
    sequence: int,
    name: str,
    data: dict[str, object] | None = None,
) -> AgentEvent:
    return AgentEvent(
        run_id="w14-session-05-01",
        sequence=sequence,
        event=name,  # type: ignore[arg-type]
        occurred_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        data=data or {},
    )


def test_session_05_fixture_matrix_has_twelve_cases() -> None:
    assert len(SESSION_05_SAMPLES) == 12
    assert {
        sample.expected_category for sample in SESSION_05_SAMPLES
    } == {"billing", "account", "product", "technical", "other"}
    assert sum("missing" in sample.acceptance_tags for sample in SESSION_05_SAMPLES) == 2
    assert sum("high_risk" in sample.acceptance_tags for sample in SESSION_05_SAMPLES) == 2
    assert sum("long_input" in sample.acceptance_tags for sample in SESSION_05_SAMPLES) == 1
    assert (
        sum(
            "unrelated_or_ambiguous" in sample.acceptance_tags
            for sample in SESSION_05_SAMPLES
        )
        == 2
    )


def test_acceptance_reports_missing_evidence_separately() -> None:
    sample = SESSION_05_SAMPLES[0]
    failures = evaluate_case(
        sample,
        {
            "run_id": "w14-session-05-01",
            "category": "billing",
            "priority": "normal",
            "status": "completed",
            "draft_response": "回复内容。",
            "evidence_refs": [],
        },
        ["normalize_ticket", "classify_ticket", "response_subgraph"],
        [
            _event(0, "text", {"text": "回复内容。"}),
            _event(1, "done", {"status": "completed"}),
        ],
    )

    assert failures
    assert {failure["category"] for failure in failures} == {"evidence"}
