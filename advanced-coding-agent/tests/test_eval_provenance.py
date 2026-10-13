"""Reference traces must never be promoted to measured acceptance evidence."""

from pathlib import Path

import pytest
from advanced_coding_agent.long_horizon.eval import (
    LongHorizonEvalReport,
    LongHorizonEvalValidationError,
    build_reference_long_horizon_eval,
)
from advanced_coding_agent.multi_agent.eval import (
    load_eval_suite,
    observation_from_long_horizon,
)


def test_reference_trace_is_not_ready_and_preserves_its_source():
    report = build_reference_long_horizon_eval()
    assert report.tool_call_count == 30
    assert report.kind == "fixture"
    assert not report.ready
    with pytest.raises(LongHorizonEvalValidationError, match="实测来源"):
        report.assert_ready()
    restored = LongHorizonEvalReport.from_dict(report.as_dict())
    assert restored.kind == "fixture" and not restored.ready


def test_legacy_trace_without_provenance_is_not_certified():
    payload = build_reference_long_horizon_eval().as_dict()
    del payload["kind"]
    restored = LongHorizonEvalReport.from_dict(payload)
    assert restored.kind == "estimate" and not restored.ready


def test_w18_conversion_cannot_promote_a_reference_trace():
    suite = load_eval_suite(
        Path(__file__).resolve().parents[1] / "evals/cases/w18_session_01.json"
    )
    report = build_reference_long_horizon_eval()
    observation = observation_from_long_horizon(
        suite,
        suite.cases[0].profile.case_id,
        report,
        wall_clock_seconds=1,
        workspace_snapshot="local-fixture",
        verifier_version="offline",
        verified_success=True,
        evidence_refs=("local:verifier",),
    )
    assert observation.kind == "fixture"
    assert observation.verified_success is False
