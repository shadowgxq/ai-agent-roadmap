from src.age import is_adult


def test_people_under_eighteen_are_not_adults():
    assert is_adult(17) is False


def test_eighteen_year_old_is_an_adult():
    assert is_adult(18) is True


def test_people_over_eighteen_are_adults():
    assert is_adult(19) is True
