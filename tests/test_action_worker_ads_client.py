import datetime as dt
from types import SimpleNamespace

from services.actions import state_machine as sm
from services.actions.worker import AdsActionClient, persist_rotated_refresh_token


class FakeAds:
    def __init__(self):
        self.calls = []
        self.credentials = SimpleNamespace(refresh_token="rotated-token")
        self.connection_id = "conn-1"

    def update_bid(self, entity_id, new_bid, dry_run=True):
        self.calls.append(("bid", entity_id, new_bid, dry_run))
        return {"ok": True}

    def update_placement_modifier(self, campaign_id, placement, new_percentage, current_percentage, dry_run=True):
        self.calls.append(("placement", campaign_id, placement, new_percentage, current_percentage, dry_run))
        return {"ok": True}


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


def action(action_type="set_bid", entity_type="keyword"):
    return sm.Action(
        id="a1",
        tenant_id="t1",
        entity_type=entity_type,
        entity_id="k1",
        action_type=action_type,
        before_value={"value": 1.0},
        after_value={"value": 1.25},
        status=sm.Status.APPROVED,
        approved_at=dt.datetime.now(dt.timezone.utc),
    )


def test_ads_action_client_applies_keyword_bid():
    ads = FakeAds()
    result = AdsActionClient(ads).apply(action())
    assert result == {"ok": True}
    assert ads.calls == [("bid", "k1", 1.25, False)]


def test_ads_action_client_applies_placement_modifier():
    ads = FakeAds()
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.after_value = {"value": 30, "placement": "PLACEMENT_TOP"}
    AdsActionClient(ads).apply(a)
    assert ads.calls == [("placement", "c1", "PLACEMENT_TOP", 30.0, 1.0, False)]


def test_persist_rotated_refresh_token_writes_ciphertext(monkeypatch):
    conn = FakeConn()
    ads = FakeAds()
    monkeypatch.setenv("KEK_BASE64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    persist_rotated_refresh_token(conn, ads)
    assert conn.calls
    sql, params = conn.calls[0]
    assert "refresh_token_encrypted" in sql
    assert params[1] == 1
    assert params[2] == "conn-1"
    assert params[0] != b"rotated-token"
