from src.profile import display_name


def test_full_name_trims_each_component():
    assert display_name(" Ada ", " Lovelace ") == "Ada Lovelace"


def test_blank_nickname_falls_back_to_full_name():
    assert display_name("Grace", "Hopper", "   ") == "Grace Hopper"


def test_nonblank_nickname_is_trimmed():
    assert display_name("Grace", "Hopper", "  Admiral  ") == "Admiral"

