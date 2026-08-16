from src.profile import UserProfile, render_profile


def test_old_constructor_remains_compatible():
    assert render_profile(UserProfile("Ada", "ada@example.com")) == (
        "Ada <ada@example.com> [UTC]"
    )


def test_new_timezone_is_rendered():
    profile = UserProfile("Ada", "ada@example.com", timezone="Asia/Shanghai")
    assert render_profile(profile) == "Ada <ada@example.com> [Asia/Shanghai]"
