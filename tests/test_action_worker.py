import datetime as dt

import pytest

from services.actions import state_machine as sm
from services.actions import worker
from services.actions.worker import (
    DryRunActionClient,
    WorkerResult,
    apply_action,
    finish_worker_run,
    persist_action_failure_alert,
    persist_auth_failure_alert,
    require_current_live_consent,
    start_worker_run,
)
from services.rules.settings import GuardrailConfigError


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
    action, response = apply_action(
        _approved_action(), DryRunActionClient(), now=dt.datetime.now(dt.timezone.utc)
    )
    assert action.status == sm.Status.APPLIED
    assert action.applied_at is not None
    assert response["status"] == "WOULD_DO"


def test_apply_failure_marks_action_failed():
    action, response = apply_action(
        _approved_action(), FailingClient(), now=dt.datetime.now(dt.timezone.utc)
    )
    assert action.status == sm.Status.FAILED
    assert "amazon down" in action.error
    assert response is None


def test_live_drift_fails_without_overwriting():
    action, _response = apply_action(
        _approved_action(), DriftClient(), now=dt.datetime.now(dt.timezone.utc)
    )
    assert action.status == sm.Status.FAILED
    assert "drift" in action.error


def test_start_worker_run_records_running_action_worker_dataset():
    conn = FakeConn([{"id": "run-1"}])
    assert start_worker_run(conn, "T1") == "run-1"
    assert conn.queries[0][1] == ("T1", "action_worker")


def test_finish_worker_run_records_success_summary():
    conn = FakeConn()
    finish_worker_run(conn, "run-1", WorkerResult(scanned=2, applied=2))
    params = conn.queries[0][1]
    assert params[0] == "success"
    assert params[1] == 2
    assert params[2] is None
    assert params[4] == "run-1"


def test_finish_worker_run_records_failed_summary():
    conn = FakeConn()
    finish_worker_run(conn, "run-1", WorkerResult(scanned=2, applied=1, failed=1))
    params = conn.queries[0][1]
    assert params[0] == "failed"
    assert params[1] == 1


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


def _settings(**overrides):
    row = {
        "automation_enabled": True,
        "dry_run": False,
        "max_change_pct": 0.25,
        "cooldown_days": 3,
        "max_changes_per_day": 50,
        "max_budget_increase_per_day": 50.0,
        "blast_radius_pct": 0.3,
        "min_bid": 0.02,
        "max_bid": 5.0,
        "max_daily_budget": 100.0,
        "max_data_age_hours": 48,
        "settlement_lag_days": 3,
    }
    row.update(overrides)
    return row


class SettingsCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _query, _params):
        return None

    def fetchone(self):
        return self.row


class WorkerConn:
    def __init__(self, settings_row):
        self.settings_row = settings_row
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _query, _params):
        return self

    def cursor(self, **_kwargs):
        return SettingsCursor(self.settings_row)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("consent block must not roll back its audit transaction")


@pytest.mark.parametrize(
    "row",
    [None, _settings(automation_enabled=False), _settings(dry_run=True)],
)
def test_current_live_consent_fails_closed(row):
    with pytest.raises(GuardrailConfigError):
        require_current_live_consent(WorkerConn(row), "T1")


def test_current_live_consent_rejects_malformed_present_row():
    row = _settings()
    del row["dry_run"]
    with pytest.raises(GuardrailConfigError):
        require_current_live_consent(WorkerConn(row), "T1")


def _wire_run(monkeypatch, conn, actions):
    monkeypatch.setattr(worker.psycopg, "connect", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(worker, "start_worker_run", lambda *_args: "run-1")
    monkeypatch.setattr(worker, "fetch_approved", lambda *_args: actions)
    monkeypatch.setattr(worker, "finish_worker_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "persist_apply_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "persist_action_failure_alert", lambda *_args: False)


def test_live_block_honors_settings_changed_after_approval_before_credentials(monkeypatch):
    conn = WorkerConn(_settings(automation_enabled=False))
    action = _approved_action()
    _wire_run(monkeypatch, conn, [action])
    monkeypatch.setattr(
        worker,
        "load_ads_client",
        lambda *_args: pytest.fail("credentials must not load when consent is blocked"),
    )
    result = worker.run_once("T1", live_ads=True)
    assert result.scanned == 1
    assert result.failed == 1
    assert result.applied == 0
    assert action.status == sm.Status.FAILED
    assert action.error.startswith("guardrail:")
    assert conn.committed is True


def test_empty_live_batch_never_loads_credentials(monkeypatch):
    conn = WorkerConn(None)
    _wire_run(monkeypatch, conn, [])
    monkeypatch.setattr(
        worker,
        "load_ads_client",
        lambda *_args: pytest.fail("empty batch must not load credentials"),
    )
    result = worker.run_once("T1", live_ads=True)
    assert result.scanned == 0
    assert result.failed == 0
    assert conn.committed is True


def test_authorized_live_path_uses_injected_client(monkeypatch):
    conn = WorkerConn(_settings())
    action = _approved_action()
    _wire_run(monkeypatch, conn, [action])
    result = worker.run_once("T1", live_ads=True, client=DryRunActionClient())
    assert result.applied == 1
    assert result.failed == 0
