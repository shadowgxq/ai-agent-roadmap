import asyncio
from copy import deepcopy
import pytest
from support_agent.evaluation.experiments import run_experiments, compare


def test_two_local_improvements_and_one_negative_control_are_measured():
    results = asyncio.run(run_experiments())
    assert results["reports"]["baseline"]["passed_count"] == 29
    assert results["reports"]["smaller-context"]["passed_count"] == 30
    assert results["comparisons"]["less-noise"]["local_fixture_improvement"]
    assert results["comparisons"]["smaller-context"]["local_fixture_improvement"]
    assert not results["comparisons"]["over-filtered"]["local_fixture_improvement"]
    assert all(row["cost_delta_usd"] is None and not row["production_adopted"] for row in results["comparisons"].values())
    candidate = deepcopy(results["reports"]["less-noise"])
    candidate["configuration"]["extra_variable"] = True
    with pytest.raises(ValueError, match="one"):
        compare(results["reports"]["baseline"], candidate)
