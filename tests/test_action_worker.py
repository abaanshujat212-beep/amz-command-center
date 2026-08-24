import datetime as dt

from services.actions import state_machine as sm
from services.actions.worker import DryRunActionClient, apply_action


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
