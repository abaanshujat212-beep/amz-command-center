import datetime as dt
from types import SimpleNamespace

from services.actions import state_machine as sm
from services.actions.worker import AdsActionClient, persist_rotated_refresh_token


class FakeAds:
    def __init__(self):
        self.calls = []
        self.credentials = SimpleNamespace(refresh_token="rotated-token")
        self.connection_id = "conn-1"

    def keyword_bid(self, keyword_id):
        self.calls.append(("read_bid", keyword_id))
        return {"value": 1.0}

    def target_bid(self, target_id):
        self.calls.append(("read_target_bid", target_id))
        return {"value": 0.8}

    def placement_modifier(self, campaign_id, placement):
        self.calls.append(("read_placement", campaign_id, placement))
        return {"value": 15.0, "placement": placement}

    def update_bid(self, entity_id, new_bid, dry_run=True):
        self.calls.append(("bid", entity_id, new_bid, dry_run))
        return {"ok": True}

    def update_target_bid(self, entity_id, new_bid, dry_run=True):
        self.calls.append(("target_bid", entity_id, new_bid, dry_run))
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


def test_ads_action_client_reads_keyword_bid_before_apply():
    ads = FakeAds()
    assert AdsActionClient(ads).read_before_value(action()) == {"value": 1.0}
    assert ads.calls == [("read_bid", "k1")]


def test_ads_action_client_reads_placement_modifier_before_apply():
    ads = FakeAds()
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.after_value = {"value": 30, "placement": "PLACEMENT_TOP"}
    assert AdsActionClient(ads).read_before_value(a) == {"value": 15.0, "placement": "PLACEMENT_TOP"}
    assert ads.calls == [("read_placement", "c1", "PLACEMENT_TOP")]


def test_ads_action_client_applies_keyword_bid():
    ads = FakeAds()
    result = AdsActionClient(ads).apply(action())
    assert result == {"ok": True}
    assert ads.calls == [("bid", "k1", 1.25, False)]


def test_target_bid_uses_target_read_and_update_endpoints():
    ads = FakeAds()
    target = action(entity_type="target")
    assert AdsActionClient(ads).read_before_value(target) == {"value": 0.8}
    AdsActionClient(ads).apply(target)
    assert ads.calls == [
        ("read_target_bid", "k1"),
        ("target_bid", "k1", 1.25, False),
    ]


def test_unsupported_live_action_fails_before_any_ads_call():
    ads = FakeAds()
    unsupported = action(action_type="set_budget", entity_type="campaign")
    try:
        AdsActionClient(ads).read_before_value(unsupported)
    except NotImplementedError as exc:
        assert "intentionally blocked" in str(exc)
    else:
        raise AssertionError("unsupported action should be blocked")
    assert ads.calls == []


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
