from src.commands import parse_command, parse_script


def test_parse_command_keeps_legacy_behavior():
    assert parse_command("  deploy   api  ") == ["deploy", "api"]


def test_parse_script_skips_blank_and_comment_lines():
    assert parse_script("# release\ndeploy api\n\n  # note\n") == [
        ["deploy", "api"]
    ]


def test_parse_script_keeps_commands_with_extra_spaces():
    assert parse_script("build   web\ntest unit") == [
        ["build", "web"],
        ["test", "unit"],
    ]
