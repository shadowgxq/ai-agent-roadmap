from src.router import channels_for


def test_critical_incident_notifies_pager_and_email():
    assert channels_for("critical") == ["pager", "email"]


def test_normal_incident_keeps_default_email():
    assert channels_for("normal") == ["email"]
