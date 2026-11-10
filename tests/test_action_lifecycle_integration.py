import datetime as dt

from services.actions import state_machine as sm
from services.actions.audit import EventType
from services.actions.verification import MetricWindow, verify_action
from services.actions.worker import (
    AdsActionClient,
    apply_action,
    persist_apply_result,
    record_apply_start,
)


class FakeAds:
    def __init__(self):
        self.calls = []

    def keyword_bid(self, keyword_id):
        self.calls.append(("read", keyword_id))
        return {"value": 1.0}

    def update_bid(self, keyword_id, value, *, dry_run):
        self.calls.append(("apply", keyword_id, value, dry_run))
        return {"status": "SUCCESS"}


class FakeConn:
    def execute(self, sql, params):
        return None


def test_approved_action_runs_read_apply_audit_and_verification_seam(monkeypatch):
    now = dt.datetime(2026, 1, 20, tzinfo=dt.timezone.utc)
    action = sm.Action(
        id="action-1",
        tenant_id="tenant-1",
        entity_type="keyword",
        entity_id="keyword-1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        requested_at=now - dt.timedelta(minutes=1),
        status=sm.Status.PENDING,
        idempotency_key="idempotency-1",
    )
    sm.approve(action, approver_id="admin-1", approver_role="admin", now=now)

    events = []
    monkeypatch.setattr("services.actions.worker.append_event", lambda _conn, event: events.append(event))
    monkeypatch.setattr("services.actions.verification.append_event", lambda _conn, event: events.append(event))
    windows = iter((
        MetricWindow(cost=10, sales=100, clicks=100, orders=5),
        MetricWindow(cost=7, sales=100, clicks=100, orders=6),
    ))
    monkeypatch.setattr("services.actions.verification.performance_window", lambda *_: next(windows))
    ads = FakeAds()
    client = AdsActionClient(ads, "LIVE_READY", "AUTHORIZED_LIVE_WRITE")
    conn = FakeConn()

    record_apply_start(conn, action, correlation_key="run-1")
    updated, response = apply_action(action, client, now=now)
    persist_apply_result(conn, updated, response, correlation_key="run-1")

    assert updated.status is sm.Status.APPLIED
    assert response == {"status": "SUCCESS"}
    assert ads.calls == [("read", "keyword-1"), ("apply", "keyword-1", 1.1, False)]

    verified = verify_action(conn, updated, now=now + dt.timedelta(days=7))

    assert verified.status is sm.Status.VERIFIED
    assert verified.outcome == "improved"
    assert [event.event_type for event in events] == [
        EventType.APPLY_REQUESTED,
        EventType.APPLY_STARTED,
        EventType.APPLY_SUCCEEDED,
        EventType.VERIFICATION_SCHEDULED,
        EventType.VERIFICATION_CHECKPOINT,
        EventType.VERIFICATION_CHECKPOINT,
        EventType.VERIFICATION_RESULT,
        EventType.VERIFICATION_TERMINAL,
    ]


def test_drift_is_audited_and_provider_write_never_runs(monkeypatch):
    now = dt.datetime(2026, 1, 20, tzinfo=dt.timezone.utc)
    action = sm.Action(
        id="action-drift",
        tenant_id="tenant-1",
        entity_type="keyword",
        entity_id="keyword-1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        requested_at=now - dt.timedelta(minutes=1),
        status=sm.Status.PENDING,
        idempotency_key="idempotency-drift",
    )
    sm.approve(action, approver_id="admin-1", approver_role="admin", now=now)

    class ChangedAds(FakeAds):
        def keyword_bid(self, keyword_id):
            self.calls.append(("read", keyword_id))
            return {"value": 0.9}

        def update_bid(self, keyword_id, value, *, dry_run):
            raise AssertionError("drift must block before provider write")

    events = []
    monkeypatch.setattr("services.actions.worker.append_event", lambda _conn, event: events.append(event))
    conn = FakeConn()
    ads = ChangedAds()
    record_apply_start(conn, action, correlation_key="run-drift")
    updated, response = apply_action(
        action,
        AdsActionClient(ads, "LIVE_READY", "AUTHORIZED_LIVE_WRITE"),
        now=now,
    )
    persist_apply_result(conn, updated, response, correlation_key="run-drift")

    assert updated.status is sm.Status.FAILED
    assert updated.error.startswith("drift:")
    assert response is None
    assert ads.calls == [("read", "keyword-1")]
    assert events[-1].event_type is EventType.DRIFT_BLOCKED
