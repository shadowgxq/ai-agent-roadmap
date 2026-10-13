import asyncio
from copy import deepcopy
import pytest

from support_agent.evaluation.catalog import load_catalog
from support_agent.evaluation.offline import execute_offline
from support_agent.evaluation.report import make_report, assess
from support_agent.evaluation_cli import run_offline


def test_all_thirty_cases_execute_and_missing_cost_is_not_zero():
    manifest, cases, corpus = load_catalog()
    observations = asyncio.run(run_offline(manifest, cases, corpus))
    report = make_report(manifest, cases, observations)
    assert report["case_count"] == 30 and report["source"] == "offline"
    assert report["average_cost_usd"] is None and report["cost_measured_cases"] == 0
    assert report["production_quality_verified"] is False
    assert report["passed_count"] >= 29
    # A local lexical fixture can return unrelated policy snippets for generic
    # words. The report must expose that failure instead of editing expected labels.
    assert report["results"][-2]["passed"] is False


def test_unapproved_write_and_missing_terminal_event_are_reported():
    manifest, cases, corpus = load_catalog()
    case = next(case for case in cases if case.id == "approve-refund")
    row = asyncio.run(execute_offline(case, manifest, corpus, "test"))
    assert assess(case, row)["passed"]
    row["approval_count"] = 0
    row["unauthorized_writes"] = 1
    row["events"] = row["events"][:-1]
    assert {"approval", "security", "infra"} <= set(assess(case, row)["failure_categories"])


def test_duplicate_checkpoint_and_nan_cost_are_rejected():
    manifest, cases, corpus = load_catalog()
    rows = asyncio.run(run_offline(manifest, cases, corpus))
    invalid = deepcopy(rows)
    invalid[1]["thread_id"] = invalid[0]["thread_id"]
    with pytest.raises(ValueError, match="identities"):
        make_report(manifest, cases, invalid)
    rows[0]["cost_usd"] = float("nan")
    with pytest.raises(ValueError, match="cost"):
        make_report(manifest, cases, rows)
