"""Single-variable comparisons; offline context size is a proxy, never dollar savings."""

from .catalog import load_catalog
from .report import make_report


def compare(baseline: dict, candidate: dict) -> dict:
    if baseline["snapshots"] != candidate["snapshots"] or baseline["source"] != candidate["source"]:
        raise ValueError("Experiments changed cases, corpus or measurement source")
    if baseline["model"] != candidate["model"] or baseline["budget"] != candidate["budget"]:
        raise ValueError("Keep model and budgets fixed")
    changed = [key for key in baseline["configuration"].keys() | candidate["configuration"].keys()
               if baseline["configuration"].get(key) != candidate["configuration"].get(key)]
    if len(changed) != 1:
        raise ValueError("Change exactly one experimental variable")
    success_gain = candidate["success_rate"] - baseline["success_rate"]
    precision_gain = candidate["retrieval_precision"] - baseline["retrieval_precision"]
    context_delta = candidate["mean_context_characters"] - baseline["mean_context_characters"]
    no_regression = success_gain >= 0 and candidate["tool_approval_violations"] <= baseline["tool_approval_violations"]
    useful = no_regression and (success_gain > 0 or precision_gain > 0 or context_delta < 0)
    measured_cost = baseline["average_cost_usd"] is not None and candidate["average_cost_usd"] is not None
    return {"changed_variable": changed[0], "success_gain": success_gain, "precision_gain": precision_gain,
            "context_character_delta": context_delta, "local_fixture_improvement": useful,
            "cost_delta_usd": candidate["average_cost_usd"] - baseline["average_cost_usd"] if measured_cost else None,
            "production_adopted": False, "decision": "requires-production-evidence" if useful else "reject"}


async def run_experiments():
    from support_agent.evaluation_cli import run_offline
    manifest, cases, corpus = load_catalog()
    configurations = {"baseline": {"top_k": 5, "min_overlap": 1},
                      "less-noise": {"top_k": 5, "min_overlap": 2},
                      "smaller-context": {"top_k": 1, "min_overlap": 2},
                      "over-filtered": {"top_k": 5, "min_overlap": 100}}
    reports = {}
    for name, config in configurations.items():
        rows = await run_offline(manifest, cases, corpus, **config)
        report = make_report(manifest, cases, rows) | {"configuration": config}
        # Preserve observed metrics and per-case results, not duplicate policy text 4 times.
        report["observations"] = [{key: row.get(key) for key in ("case_id", "source", "run_id", "thread_id", "graph_status", "model_calls", "writes", "context_characters", "latency_seconds", "cost_usd", "error_code")} for row in rows]
        reports[name] = report
    comparisons = {"less-noise": compare(reports["baseline"], reports["less-noise"]),
                   "smaller-context": compare(reports["less-noise"], reports["smaller-context"]),
                   "over-filtered": compare(reports["less-noise"], reports["over-filtered"])}
    return {"source": "offline", "production_quality_verified": False,
            "reports": reports, "comparisons": comparisons}
