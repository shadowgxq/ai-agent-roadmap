import pytest

from src.policy import permissions_for


def test_viewer_can_read():
    assert permissions_for("viewer") == {"read"}


def test_editor_inherits_viewer_permissions():
    assert permissions_for("editor") == {"read", "write"}


def test_admin_inherits_entire_role_chain():
    assert permissions_for("admin") == {"read", "write", "manage"}


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        permissions_for("owner")
