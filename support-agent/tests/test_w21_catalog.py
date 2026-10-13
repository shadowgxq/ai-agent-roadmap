from support_agent.evaluation.catalog import load_catalog, isolated_ids


def test_frozen_catalog_counts_and_independent_run_identities():
    manifest, cases, corpus = load_catalog()
    assert len(cases) == 30 and corpus and manifest["budget"]["max_tool_calls"] == 1
    first, second = isolated_ids(cases[0], "a"), isolated_ids(cases[0], "a")
    assert first["thread_id"] != second["thread_id"] and first["run_id"] != second["run_id"]
    assert isolated_ids(cases[0], "a")["organization_id"] != isolated_ids(cases[0], "b")["organization_id"]
