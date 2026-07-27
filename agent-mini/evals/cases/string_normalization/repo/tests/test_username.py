from src.username import normalize_username


def test_normalizes_case_and_outer_whitespace():
    assert normalize_username("  Alice ") == "alice"


def test_collapses_repeated_inner_whitespace():
    assert normalize_username("Bob   Smith") == "bob smith"


def test_keeps_single_inner_spaces():
    assert normalize_username("Carol Jones") == "carol jones"
