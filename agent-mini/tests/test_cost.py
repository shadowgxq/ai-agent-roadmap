import json
from pathlib import Path

import pytest

from evals.compare import compare_reports
from evals.run import EvalResult, write_report
from src.agent.config import AgentSettings
from src.agent.cost import CostCalculator, PriceTable
from src.agent.loop import RunStats, UsageTokens


def write_prices(path: Path, *, flash_prices: bool = True) -> Path:
    flash = (
        "input_per_million: 3.0\n"
        "    output_per_million: 4.0\n"
        "    cache_read_per_million: 0.5\n"
        "    cache_creation_per_million: 0.25"
        if flash_prices
        else
        "input_per_million: null\n"
        "    output_per_million: null\n"
        "    cache_read_per_million: null\n"
        "    cache_creation_per_million: null"
    )
    path.write_text(
        "version: 1\n"
        "currency: USD\n"
        "models:\n"
        "  pro:\n"
        "    input_per_million: 1.0\n"
        "    output_per_million: 2.0\n"
        "    cache_read_per_million: 0.5\n"
        "    cache_creation_per_million: 0.25\n"
        "  flash:\n"
        f"    {flash}\n",
        encoding="utf-8",
    )
    return path


def make_calculator(path: Path, *, small_model: str = "flash") -> CostCalculator:
    settings = AgentSettings(
        _env_file=None,
        api_key="test-key",
        model="pro",
        main_model="pro",
        small_model=small_model,
        pricing_file=path,
    )
    return CostCalculator.from_settings(settings)


def test_pricing_file_can_be_overridden_by_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_path = write_prices(tmp_path / "prices.yaml")
    monkeypatch.setenv("PRICING_FILE", str(pricing_path))

    settings = AgentSettings(_env_file=None, api_key="test-key")

    assert settings.resolved_pricing_file == pricing_path


def test_price_table_loads_yaml_and_rejects_invalid_values(tmp_path: Path) -> None:
    path = write_prices(tmp_path / "prices.yaml")
    table = PriceTable.load(path)

    assert table.currency == "USD"
    assert table.price_for("pro") is not None
    assert table.price_for("unknown") is None

    negative = tmp_path / "negative.yaml"
    negative.write_text(
        "version: 1\ncurrency: USD\nmodels:\n"
        "  pro:\n"
        "    input_per_million: -1\n"
        "    output_per_million: 2\n"
        "    cache_read_per_million: null\n"
        "    cache_creation_per_million: null\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="非负"):
        PriceTable.load(negative)

    invalid_field = tmp_path / "invalid-field.yaml"
    invalid_field.write_text(
        "version: 1\ncurrency: USD\nmodels:\n"
        "  pro:\n"
        "    input_per_million: 1\n"
        "    output_per_million: 2\n"
        "    cache_read_per_million: 0\n"
        "    cache_creation_per_million: 0\n"
        "    typo: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未知价格字段"):
        PriceTable.load(invalid_field)


def test_price_table_rejects_duplicate_model_names(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "version: 1\ncurrency: USD\nmodels:\n"
        "  pro: &first\n"
        "    input_per_million: 1\n"
        "    output_per_million: 2\n"
        "    cache_read_per_million: 0\n"
        "    cache_creation_per_million: 0\n"
        "  pro: *first\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重复字段"):
        PriceTable.load(path)


def test_breakdown_separates_agent_compact_router_and_judge_costs(
    tmp_path: Path,
) -> None:
    calculator = make_calculator(write_prices(tmp_path / "prices.yaml"))
    stats = RunStats(
        turns=1,
        selected_model="pro",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        compact_calls=1,
        compact_input_tokens=1_000_000,
        router_calls=1,
        router_model="flash",
        router_input_tokens=1_000_000,
        router_output_tokens=1_000_000,
    )

    breakdown = calculator.breakdown(
        stats,
        judge_usage=UsageTokens(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        ),
        judge_model="pro",
    )

    assert breakdown.available is True
    assert breakdown.agent_usd == pytest.approx(3.75)
    assert breakdown.compact_usd == pytest.approx(1.0)
    assert breakdown.router_usd == pytest.approx(7.0)
    assert breakdown.judge_usd == pytest.approx(3.0)
    assert breakdown.task_usd == pytest.approx(4.75)
    assert breakdown.total_usd == pytest.approx(14.75)
    assert breakdown.total_usd == pytest.approx(
        breakdown.task_usd + breakdown.router_usd + breakdown.judge_usd
    )
    assert calculator.estimate_usage(
        UsageTokens(input_tokens=1_000_000), "pro"
    ) == pytest.approx(1.0)
    assert breakdown.to_dict()["missing_prices"] == []


def test_missing_model_price_is_explicitly_unavailable(tmp_path: Path) -> None:
    calculator = make_calculator(
        write_prices(tmp_path / "prices.yaml", flash_prices=False),
    )
    stats = RunStats(
        turns=1,
        selected_model="flash",
        input_tokens=10,
        output_tokens=2,
    )

    breakdown = calculator.breakdown(stats)

    assert breakdown.available is False
    assert breakdown.agent_usd is None
    assert breakdown.task_usd is None
    assert breakdown.total_usd is None
    assert any(
        "flash.input_per_million" in item for item in breakdown.missing_prices)


def test_eval_report_contains_nested_and_legacy_cost_fields(
    tmp_path: Path,
) -> None:
    result = EvalResult(
        case_name="cost_case",
        eval_type="behavior",
        status="pass",
        cost_usd=0.011,
        cost={
            "currency": "USD",
            "available": True,
            "agent_usd": 0.01,
            "compact_usd": 0.0,
            "router_usd": 0.001,
            "judge_usd": 0.0,
            "task_usd": 0.01,
            "total_usd": 0.011,
            "missing_prices": [],
        },
    )
    report_path = write_report(
        tmp_path / "report.json",
        experiment="candidate",
        suite="core",
        selected_cases=[Path("cost_case")],
        results=[result],
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["cost"]["total_usd"] == pytest.approx(0.011)
    assert payload["total_cost_usd"] == pytest.approx(0.011)
    assert payload["router_cost_usd"] == pytest.approx(0.001)
    assert payload["summary"]["cost"]["agent_usd"] == pytest.approx(0.01)
    assert payload["results"][0]["task_cost_usd"] == pytest.approx(0.01)

    old_report = {
        "experiment": "baseline",
        "summary": {"cost_usd": 0.02, "avg_cost_usd": 0.02},
        "results": [],
    }
    comparison = compare_reports(old_report, payload)
    assert comparison["cost"]["total_usd"]["baseline"] == pytest.approx(0.02)
    assert comparison["cost"]["total_usd"]["candidate"] == pytest.approx(0.011)
