import datetime as dt

from services.actions import state_machine as sm
from services.actions.worker import (
    DryRunActionClient,
    apply_action,
    persist_action_failure_alert,
    persist_auth_failure_alert,
)


class FailingClient:
    def read_before_value(self, action):
        return action.before_value

    def apply(self, action):
        raise RuntimeError("amazon down")

    def rollback(self, action):
        return {}


class DriftClient:
    def read_before_value(self, action):
        return {"value": 1.25}

    def apply(self, action):
        return {"status": "OK"}

    def rollback(self, action):
        return {}


class FakeConn:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None


def _approved_action():
    return sm.Action(
        id="A1",
        tenant_id="T1",
        entity_type="keyword",
        entity_id="K1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        status=sm.Status.APPROVED,
        approved_by="U1",
        approved_at=dt.datetime.now(dt.timezone.utc),
    )


def test_dry_run_client_marks_approved_action_applied():
    action, response = apply_action(_approved_action(), DryRunActionClient(), now=dt.datetime.now(dt.timezone.utc))
    assert action.status == sm.Status.APPLIED
    assert action.applied_at is not None
    assert response["status"] == "WOULD_DO"


def test_apply_failure_marks_action_failed():
    action, response = apply_action(_approved_action(), FailingClient(), now=dt.datetime.now(dt.timezone.utc))
    assert action.status == sm.Status.FAILED
    assert "amazon down" in action.error
    assert response is None


def test_live_drift_fails_without_overwriting():
    action, _response = apply_action(_approved_action(), DriftClient(), now=dt.datetime.now(dt.timezone.utc))
    assert action.status == sm.Status.FAILED
    assert "drift" in action.error


def test_persist_action_failure_alert_inserts_for_failed_action():
    conn = FakeConn()
    action = _approved_action()
    action.status = sm.Status.FAILED
    action.error = "amazon down"
    assert persist_action_failure_alert(conn, action) is True
    assert conn.queries[-1][1][3].startswith("Action A1 failed")
    assert conn.queries[-1][1][5] == "A1"


def test_persist_action_failure_alert_skips_existing_open_alert():
    conn = FakeConn([{"id": "alert-1"}])
    action = _approved_action()
    action.status = sm.Status.FAILED
    action.error = "amazon down"
    assert persist_action_failure_alert(conn, action) is False
    assert len(conn.queries) == 1


def test_persist_action_failure_alert_skips_non_failed_action():
    conn = FakeConn()
    action = _approved_action()
    assert persist_action_failure_alert(conn, action) is False
    assert conn.queries == []


def test_persist_auth_failure_alert_inserts_provider_alert():
    conn = FakeConn()
    assert persist_auth_failure_alert(conn, "T1", "missing token") is True
    assert conn.queries[-1][1][1] == "auth_expired"
    assert conn.queries[-1][1][5] == "ads_api"


def test_persist_auth_failure_alert_skips_duplicate_provider_alert():
    conn = FakeConn([{"id": "alert-1"}])
    assert persist_auth_failure_alert(conn, "T1", "missing token") is False
    assert len(conn.queries) == 1
