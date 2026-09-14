import datetime as dt

from services.actions import state_machine as sm
from services.actions.audit import EventType
from services.actions.lifecycle_audit import record_retry, record_retry_attempt, rollback_action


class FakeConn:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        return self


class RollbackClient:
    def __init__(self, fail=False):
        self.fail = fail

    def rollback(self, _action):
        if self.fail:
            raise RuntimeError("rollback failed")
        return {"status": "ok"}


def failed_action():
    return sm.Action(
        id="a1",
        tenant_id="t1",
        entity_type="keyword",
        entity_id="k1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        status=sm.Status.FAILED,
        idempotency_key="idem-1",
    )


def applied_action():
    value = failed_action()
    value.status = sm.Status.APPLIED
    return value


def test_retry_schedule_attempt_and_exhaustion(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.lifecycle_audit.append_event", lambda _conn, event: events.append(event))
    conn = FakeConn()
    item = failed_action()
    record_retry_attempt(conn, item, attempt=1, correlation_key="retry-run")
    record_retry(conn, item, attempt=1, correlation_key="retry-run")
    exhausted = failed_action()
    record_retry(conn, exhausted, attempt=3, correlation_key="retry-run", exhausted=True)
    assert [event.event_type for event in events] == [
        EventType.RETRY_ATTEMPTED,
        EventType.RETRY_SCHEDULED,
        EventType.RETRY_EXHAUSTED,
    ]
    assert conn.queries


def test_rollback_request_and_success_or_failure(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.lifecycle_audit.append_event", lambda _conn, event: events.append(event))
    rollback_action(
        FakeConn(),
        applied_action(),
        RollbackClient(),
        now=dt.datetime.now(dt.timezone.utc),
        correlation_key="rollback-1",
    )
    rollback_action(
        FakeConn(),
        applied_action(),
        RollbackClient(fail=True),
        now=dt.datetime.now(dt.timezone.utc),
        correlation_key="rollback-2",
    )
    assert [event.event_type for event in events] == [
        EventType.ROLLBACK_REQUESTED,
        EventType.ROLLBACK_SUCCEEDED,
        EventType.ROLLBACK_REQUESTED,
        EventType.ROLLBACK_FAILED,
    ]
