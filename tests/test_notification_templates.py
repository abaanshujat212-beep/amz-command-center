from services.notifications.templates import load_approved_template


class Conn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.row


def test_template_lookup_prefers_event_specific_approved_template():
    conn = Conn({"id": "template"})
    assert load_approved_template(conn, "tenant", "pipeline_failed", "email") == {"id": "template"}
    sql, params = conn.calls[0]
    assert "status='APPROVED'" in sql
    assert "event_type in (%s,'*')" in sql
    assert params == ("tenant", "email", "pipeline_failed", "pipeline_failed")


def test_in_app_and_unknown_channels_do_not_query_templates():
    conn = Conn({"id": "template"})
    assert load_approved_template(conn, "tenant", "pipeline_failed", "in_app") is None
    assert load_approved_template(conn, "tenant", "pipeline_failed", "fax") is None
    assert conn.calls == []
