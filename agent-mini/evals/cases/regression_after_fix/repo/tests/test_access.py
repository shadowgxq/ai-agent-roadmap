from src.access import allowed


def test_viewer_can_read_but_cannot_write():
    assert allowed("viewer", "read") is True
    assert allowed("viewer", "write") is False


def test_editor_can_read_and_write_but_not_delete():
    assert allowed("editor", "read") is True
    assert allowed("editor", "write") is True
    assert allowed("editor", "delete") is False


def test_admin_keeps_full_access():
    assert allowed("admin", "read") is True
    assert allowed("admin", "write") is True
    assert allowed("admin", "delete") is True
