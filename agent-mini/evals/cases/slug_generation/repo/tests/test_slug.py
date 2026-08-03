from src.slug import slugify


def test_lowercases_and_joins_words():
    assert slugify("Hello World") == "hello-world"


def test_removes_punctuation_and_collapses_separators():
    assert slugify("  Agent: Build, Test!  ") == "agent-build-test"


def test_empty_title_returns_empty_slug():
    assert slugify(" !!! ") == ""
