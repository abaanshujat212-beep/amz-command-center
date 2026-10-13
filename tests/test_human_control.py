import datetime as dt

from services.actions.human_control import active_control, complete_one_time_control


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query, params):
        self.queries.append((query, params))
        return Result(self.row)


NOW = dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)


def test_lock_blocks_automation_but_allows_its_linked_human_action():
    row = {
        "id": "c1",
        "duration": "persistent",
        "expires_at": None,
        "reason": "operator correction",
        "state": "LOCKED",
    }
    assert active_control(
        Connection(row), tenant_id="t", entity_type="keyword", entity_id="k", now=NOW
    ).blocked
    linked = active_control(
        Connection(row),
        tenant_id="t",
        entity_type="keyword",
        entity_id="k",
        action_control_id="c1",
        now=NOW,
    )
    assert not linked.blocked
    assert linked.state == "LOCKED"


def test_temporary_override_becomes_review_due_and_resume_is_automated():
    expired = {
        "id": "c1",
        "duration": "temporary",
        "expires_at": NOW - dt.timedelta(seconds=1),
        "reason": "review",
        "state": "HUMAN_OVERRIDE",
    }
    assert (
        active_control(
            Connection(expired),
            tenant_id="t",
            entity_type="search_term",
            entity_id="bad term",
            now=NOW,
        ).state
        == "REVIEW_DUE"
    )
    resumed = {**expired, "state": "AUTOMATED"}
    assert not active_control(
        Connection(resumed), tenant_id="t", entity_type="search_term", entity_id="bad term", now=NOW
    ).blocked


def test_one_time_control_returns_to_automation_only_after_completion():
    conn = Connection({"duration": "one_time", "created_by": "u1"})
    complete_one_time_control(conn, tenant_id="t", control_id="c1")
    assert len(conn.queries) == 2
    assert "'AUTOMATED'" in conn.queries[1][0]
