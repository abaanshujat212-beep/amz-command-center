import datetime as dt

from services.actions import state_machine as sm
from services.actions.audit import EventType
from services.actions.worker import persist_apply_result, record_apply_start


class FakeResult:
    def fetchone(self):
        return None


class FakeConn:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        return FakeResult()


def action(status=sm.Status.APPROVED, error=None):
    return sm.Action(
        id="a1",
        tenant_id="t1",
        entity_type="keyword",
        entity_id="k1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        status=status,
        error=error,
        applied_at=dt.datetime.now(dt.timezone.utc) if status == sm.Status.APPLIED else None,
        idempotency_key="idem-1",
    )


def test_apply_start_emits_requested_and_started(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.worker.append_event", lambda _conn, event: events.append(event))
    record_apply_start(FakeConn(), action(), correlation_key="run-1")
    assert [event.event_type for event in events] == [EventType.APPLY_REQUESTED, EventType.APPLY_STARTED]


def test_apply_result_classifies_success_failure_and_drift(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.worker.append_event", lambda _conn, event: events.append(event))
    for item in (
        action(sm.Status.APPLIED),
        action(sm.Status.FAILED, "amazon down"),
        action(sm.Status.FAILED, "drift: baseline changed"),
    ):
        persist_apply_result(FakeConn(), item, {"status": "ok"}, correlation_key="run-1")
    assert [event.event_type for event in events] == [
        EventType.APPLY_SUCCEEDED,
        EventType.APPLY_FAILED,
        EventType.DRIFT_BLOCKED,
    ]
