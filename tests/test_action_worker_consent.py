import datetime as dt

import pytest

from services.actions import state_machine as sm
from services.actions import worker
from services.actions.worker import DryRunActionClient, require_current_live_consent
from services.rules.settings import GuardrailConfigError


def settings(**overrides):
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


def approved_action():
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


@pytest.mark.parametrize(
    "row",
    [None, settings(automation_enabled=False), settings(dry_run=True)],
)
def test_current_live_consent_fails_closed(row):
    with pytest.raises(GuardrailConfigError):
        require_current_live_consent(WorkerConn(row), "T1")


def test_current_live_consent_rejects_malformed_present_row():
    row = settings()
    del row["dry_run"]
    with pytest.raises(GuardrailConfigError):
        require_current_live_consent(WorkerConn(row), "T1")


def wire_run(monkeypatch, conn, actions):
    monkeypatch.setattr(worker.psycopg, "connect", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(worker, "start_worker_run", lambda *_args: "run-1")
    monkeypatch.setattr(worker, "fetch_approved", lambda *_args: actions)
    monkeypatch.setattr(worker, "finish_worker_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "record_apply_start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "persist_apply_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "persist_action_failure_alert", lambda *_args: False)


def test_changed_settings_block_before_credentials(monkeypatch):
    conn = WorkerConn(settings(automation_enabled=False))
    action = approved_action()
    wire_run(monkeypatch, conn, [action])
    monkeypatch.setattr(
        worker,
        "load_ads_client",
        lambda *_args: pytest.fail("credentials must not load when consent is blocked"),
    )
    result = worker.run_once("T1", live_ads=True)
    assert (result.scanned, result.applied, result.failed) == (1, 0, 1)
    assert action.status == sm.Status.FAILED
    assert action.error.startswith("guardrail:")
    assert conn.committed is True


def test_empty_live_batch_never_loads_credentials(monkeypatch):
    conn = WorkerConn(None)
    wire_run(monkeypatch, conn, [])
    monkeypatch.setattr(
        worker,
        "load_ads_client",
        lambda *_args: pytest.fail("empty batch must not load credentials"),
    )
    result = worker.run_once("T1", live_ads=True)
    assert (result.scanned, result.failed) == (0, 0)
    assert conn.committed is True


def test_authorized_live_path_uses_injected_client(monkeypatch):
    conn = WorkerConn(settings())
    action = approved_action()
    wire_run(monkeypatch, conn, [action])
    result = worker.run_once("T1", live_ads=True, client=DryRunActionClient())
    assert (result.applied, result.failed) == (1, 0)
