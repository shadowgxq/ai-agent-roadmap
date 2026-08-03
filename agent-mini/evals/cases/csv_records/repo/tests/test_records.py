from src.records import parse_records


def test_parses_every_data_row():
    content = "name,city\nAlice,Hangzhou\nBob,Shanghai\n"
    assert parse_records(content) == [
        {"name": "Alice", "city": "Hangzhou"},
        {"name": "Bob", "city": "Shanghai"},
    ]


def test_parses_single_data_row():
    assert parse_records("name,city\nAlice,Hangzhou\n") == [
        {"name": "Alice", "city": "Hangzhou"}
    ]


def test_header_only_returns_empty_list():
    assert parse_records("name,city\n") == []
