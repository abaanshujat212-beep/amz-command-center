import datetime as dt

from services.actions import state_machine as sm
from services.actions.audit import EventType
from services.actions.verification import (
    ACTION_METRICS,
    MetricWindow,
    _mature,
    judge,
    placement_window,
    verify_action,
    verify_horizon,
)


class FakeConn:
    def __init__(self, windows):
        self.windows = list(windows)
        self.updates = []
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        if sql.strip().startswith("update action"):
            self.updates.append((sql, params))
        return self

    def fetchone(self):
        return self.windows.pop(0)


def test_judge_improved_when_acos_drops():
    outcome, impact = judge(
        MetricWindow(cost=50, sales=100, clicks=50, orders=5),
        MetricWindow(cost=35, sales=100, clicks=50, orders=6),
    )
    assert outcome == "improved"
    assert impact["before"]["acos"] == 0.5
    assert impact["after"]["acos"] == 0.35


def test_judge_worsened_when_acos_rises():
    outcome, _impact = judge(
        MetricWindow(cost=30, sales=100, clicks=50, orders=5),
        MetricWindow(cost=45, sales=100, clicks=50, orders=4),
    )
    assert outcome == "worsened"


def test_judge_inconclusive_without_click_volume():
    outcome, _impact = judge(
        MetricWindow(cost=1, sales=10, clicks=5, orders=1),
        MetricWindow(cost=1, sales=12, clicks=5, orders=1),
    )
    assert outcome == "inconclusive"


def test_placement_window_splits_entity_id():
    conn = FakeConn([{"cost": 10, "sales": 20, "clicks": 11, "orders": 1}])
    result = placement_window(conn, "t1", "c1:top_of_search", dt.date(2026, 8, 1), dt.date(2026, 8, 8))
    assert result.cost == 10
    assert conn.queries[0][1][1:3] == ("c1", "top_of_search")


def test_verify_action_persists_state_and_all_checkpoints(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.verification.append_event", lambda _conn, event: events.append(event))
    now = dt.datetime(2026, 8, 25, tzinfo=dt.timezone.utc)
    action = sm.Action(
        id="a1",
        tenant_id="t1",
        entity_type="keyword",
        entity_id="k1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        status=sm.Status.APPLIED,
        applied_at=now - dt.timedelta(days=8),
        idempotency_key="idem-1",
    )
    conn = FakeConn([
        {"cost": 50, "sales": 100, "clicks": 50, "orders": 5},
        {"cost": 35, "sales": 100, "clicks": 50, "orders": 6},
    ])
    updated = verify_action(conn, action, now=now)
    assert updated.status == sm.Status.VERIFIED
    assert updated.outcome == "improved"
    assert conn.updates
    assert [event.event_type for event in events] == [
        EventType.VERIFICATION_SCHEDULED,
        EventType.VERIFICATION_CHECKPOINT,
        EventType.VERIFICATION_CHECKPOINT,
        EventType.VERIFICATION_RESULT,
        EventType.VERIFICATION_TERMINAL,
    ]
    assert [event.verification_checkpoint for event in events[1:3]] == [
        "before_window_loaded",
        "after_window_loaded",
    ]


def test_horizon_is_complete_only_with_every_settled_day():
    end = dt.date(2026, 8, 8)
    assert _mature(MetricWindow(1, 2, 10, 1, 7, end - dt.timedelta(days=1)), end - dt.timedelta(days=7), end)
    assert not _mature(MetricWindow(1, 2, 10, 1, 6, end - dt.timedelta(days=1)), end - dt.timedelta(days=7), end)


def test_action_specific_metrics_do_not_claim_unrelated_signals():
    assert "cpc" in ACTION_METRICS["set_bid"]
    assert "cpc" not in ACTION_METRICS["set_budget"]
    assert ACTION_METRICS["pause"] == ("cost", "sales", "orders")


def test_immature_horizon_persists_retryable_insufficient_data():
    now = dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc)
    action = sm.Action(id="a2", tenant_id="t1", entity_type="keyword", entity_id="k1",
        action_type="set_bid", before_value={"value": 1}, after_value={"value": 1.1},
        status=sm.Status.APPLIED, applied_at=now - dt.timedelta(days=3), idempotency_key="i2")
    conn = FakeConn([
        {"cost": 1, "sales": 2, "clicks": 10, "orders": 1, "observed_days": 3, "data_through": dt.date(2026, 8, 6)},
        {"cost": 1, "sales": 2, "clicks": 10, "orders": 1, "observed_days": 2, "data_through": dt.date(2026, 8, 9)},
    ])
    assert verify_horizon(conn, action, 3, now=now) == "INSUFFICIENT_DATA"
    assert conn.queries[-1][1][3] == "INSUFFICIENT_DATA"
    assert conn.queries[-1][1][13] == "WINDOW_NOT_MATURE"


def test_mature_horizon_is_complete_and_idempotent_upsert_is_scoped():
    now = dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc)
    action = sm.Action(id="a3", tenant_id="t1", entity_type="campaign", entity_id="c1",
        action_type="set_budget", before_value={"value": 10}, after_value={"value": 12},
        status=sm.Status.APPLIED, applied_at=now - dt.timedelta(days=3), idempotency_key="i3")
    conn = FakeConn([
        {"cost": 10, "sales": 20, "clicks": 20, "orders": 2, "observed_days": 3, "data_through": dt.date(2026, 8, 6)},
        {"cost": 8, "sales": 20, "clicks": 20, "orders": 2, "observed_days": 3, "data_through": dt.date(2026, 8, 9)},
    ])
    assert verify_horizon(conn, action, 3, now=now) == "COMPLETE"
    sql, params = conn.queries[-1]
    assert "on conflict(tenant_id,action_id,horizon_days)" in sql
    assert params[3:5] == ("COMPLETE", "improved")
