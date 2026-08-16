import pytest

from src.users import create_user


def test_create_user_keeps_the_existing_return_shape():
    assert create_user("Ada", "ada@example.com", 36) == {
        "name": "Ada",
        "email": "ada@example.com",
        "age": 36,
    }


@pytest.mark.parametrize("email", ["", "ada.example.com", "@example.com"])
def test_rejects_invalid_email(email: str):
    with pytest.raises(ValueError):
        create_user("Ada", email, 36)


def test_rejects_negative_age():
    with pytest.raises(ValueError):
        create_user("Ada", "ada@example.com", -1)
