import datetime as dt

from services.actions import state_machine as sm
from services.actions.verification import MetricWindow, judge, placement_window, verify_action


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


def test_verify_action_persists_verified_status():
    now = dt.datetime(2026, 8, 25, tzinfo=dt.timezone.utc)
    applied_at = now - dt.timedelta(days=8)
    action = sm.Action(
        id="a1",
        tenant_id="t1",
        entity_type="keyword",
        entity_id="k1",
        action_type="set_bid",
        before_value={"value": 1.0},
        after_value={"value": 1.1},
        status=sm.Status.APPLIED,
        applied_at=applied_at,
    )
    conn = FakeConn([
        {"cost": 50, "sales": 100, "clicks": 50, "orders": 5},
        {"cost": 35, "sales": 100, "clicks": 50, "orders": 6},
    ])
    updated = verify_action(conn, action, now=now)
    assert updated.status == sm.Status.VERIFIED
    assert updated.outcome == "improved"
    assert conn.updates
    assert conn.updates[0][1][3]["entity_type"] == "keyword"
