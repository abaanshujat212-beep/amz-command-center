import datetime as dt
from types import SimpleNamespace

import pytest

from packages.shared.action_capabilities import capability
from services.actions import state_machine as sm
from services.actions.worker import AdsActionClient, apply_action, persist_rotated_refresh_token


class FakeAds:
    def __init__(self):
        self.calls = []
        self.credentials = SimpleNamespace(refresh_token="rotated-token")
        self.connection_id = "conn-1"
        self.state = "ENABLED"

    def keyword_bid(self, keyword_id):
        self.calls.append(("read_bid", keyword_id))
        return {"value": 1.0}

    def exact_keyword_exists(self, ad_group_id, keyword_text):
        self.calls.append(("keyword_exists", ad_group_id, keyword_text))
        return False

    def create_keyword(self, **kwargs):
        self.exact_keyword_exists(kwargs["ad_group_id"], kwargs["keyword_text"])
        self.calls.append(("create_keyword", kwargs))
        return {"ok": True}

    def target_bid(self, target_id):
        self.calls.append(("read_target_bid", target_id))
        return {"value": 0.8}

    def placement_modifier(self, campaign_id, placement):
        self.calls.append(("read_placement", campaign_id, placement))
        return {"value": 15.0, "placement": placement}

    def campaign_status(self, campaign_id):
        self.calls.append(("read_campaign_status", campaign_id))
        return {"value": self.state}

    def campaign_budget(self, campaign_id):
        self.calls.append(("read_campaign_budget", campaign_id))
        return {"value": 20.0}

    def entity_status(self, entity_type, entity_id):
        self.calls.append(("read_entity_status", entity_type, entity_id))
        return {"value": "ENABLED"}

    def ad_group_default_bid(self, ad_group_id):
        self.calls.append(("read_ad_group_bid", ad_group_id))
        return {"value": 0.75}

    def update_bid(self, entity_id, new_bid, dry_run=True):
        self.calls.append(("bid", entity_id, new_bid, dry_run))
        return {"ok": True}

    def update_target_bid(self, entity_id, new_bid, dry_run=True):
        self.calls.append(("target_bid", entity_id, new_bid, dry_run))
        return {"ok": True}

    def update_placement_modifier(self, campaign_id, placement, new_percentage, current_percentage, dry_run=True):
        self.calls.append(("placement", campaign_id, placement, new_percentage, current_percentage, dry_run))
        return {"ok": True}

    def update_campaign_status(self, campaign_id, status, dry_run=True):
        self.calls.append(("campaign_status", campaign_id, status, dry_run))
        return {"ok": True}

    def update_campaign_budget(self, campaign_id, budget, dry_run=True):
        self.calls.append(("campaign_budget", campaign_id, budget, dry_run))
        return {"ok": True}

    def update_entity_status(self, entity_type, entity_id, state, dry_run=True):
        self.calls.append(("entity_status", entity_type, entity_id, state, dry_run))
        return {"ok": True}

    def update_ad_group_default_bid(self, ad_group_id, bid, dry_run=True):
        self.calls.append(("ad_group_bid", ad_group_id, bid, dry_run))
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
        approval_confirmation="CREATE KEYWORD" if action_type == "create_keyword" else None,
    )


def live_client(ads):
    return AdsActionClient(ads, "LIVE_READY", "AUTHORIZED_LIVE_WRITE")


def test_ads_action_client_reads_keyword_bid_before_apply():
    ads = FakeAds()
    assert live_client(ads).read_before_value(action()) == {"value": 1.0}
    assert ads.calls == [("read_bid", "k1")]


def test_ads_action_client_reads_placement_modifier_before_apply():
    ads = FakeAds()
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.after_value = {"value": 30, "placement": "PLACEMENT_TOP"}
    assert live_client(ads).read_before_value(a) == {"value": 15.0, "placement": "PLACEMENT_TOP"}
    assert ads.calls == [("read_placement", "c1", "PLACEMENT_TOP")]


def test_ads_action_client_applies_keyword_bid():
    ads = FakeAds()
    result = live_client(ads).apply(action())
    assert result == {"ok": True}
    assert ads.calls == [("bid", "k1", 1.25, False)]


def test_target_bid_uses_target_read_and_update_endpoints():
    ads = FakeAds()
    target = action(entity_type="target")
    assert live_client(ads).read_before_value(target) == {"value": 0.8}
    live_client(ads).apply(target)
    assert ads.calls == [
        ("read_target_bid", "k1"),
        ("target_bid", "k1", 1.25, False),
    ]


def test_exact_keyword_harvest_rechecks_duplicates_and_creates_in_routed_group():
    ads = FakeAds()
    harvest = action("create_keyword", "search_term")
    harvest.entity_id = "hook and loop tape"
    harvest.before_value = None
    harvest.after_value = {
        "value": 0.42,
        "destination": {
            "campaign_id": "c1", "ad_group_id": "g1", "match_type": "exact", "route_code": "generic_exact"
        },
    }
    client = live_client(ads)

    assert client.read_before_value(harvest) is None
    assert client.apply(harvest) == {"ok": True}
    assert ads.calls == [
        ("keyword_exists", "g1", "hook and loop tape"),
        ("keyword_exists", "g1", "hook and loop tape"),
        ("create_keyword", {
            "campaign_id": "c1", "ad_group_id": "g1", "keyword_text": "hook and loop tape",
            "match_type": "EXACT", "bid": 0.42, "dry_run": False,
        }),
    ]


def test_exact_keyword_creation_requires_typed_approval_before_mutation():
    ads = FakeAds()
    harvest = action("create_keyword", "search_term")
    harvest.approval_confirmation = None
    harvest.before_value = None
    harvest.after_value = {
        "value": 0.42,
        "destination": {"campaign_id": "c1", "ad_group_id": "g1", "match_type": "exact"},
    }

    try:
        live_client(ads).apply(harvest)
    except RuntimeError as exc:
        assert "explicit approval confirmation" in str(exc)
    else:
        raise AssertionError("non-reversible keyword creation must require typed confirmation")
    assert ads.calls == []


def test_keyword_harvest_blocks_product_routes_and_existing_targets():
    ads = FakeAds()
    harvest = action("create_keyword", "search_term")
    harvest.before_value = None
    harvest.after_value = {"value": 0.42, "destination": {"ad_group_id": "g1", "match_type": "product"}}
    try:
        live_client(ads).read_before_value(harvest)
    except RuntimeError as exc:
        assert "exact destination" in str(exc)
    else:
        raise AssertionError("product targets must not be sent through keyword creation")

    harvest.after_value["destination"]["match_type"] = "exact"
    ads.exact_keyword_exists = lambda *_: True
    try:
        live_client(ads).read_before_value(harvest)
    except RuntimeError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing exact keyword must block the action")


def test_unsupported_live_action_fails_before_any_ads_call():
    ads = FakeAds()
    unsupported = action(action_type="archive", entity_type="campaign")
    try:
        live_client(ads).read_before_value(unsupported)
    except RuntimeError as exc:
        assert "unsupported capability" in str(exc)
    else:
        raise AssertionError("unsupported action should be blocked")
    assert ads.calls == []


def test_ads_action_client_applies_placement_modifier():
    ads = FakeAds()
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.after_value = {"value": 30, "placement": "PLACEMENT_TOP"}
    live_client(ads).apply(a)
    assert ads.calls == [("placement", "c1", "PLACEMENT_TOP", 30.0, 1.0, False)]


def test_ads_action_client_rolls_back_placement_modifier_using_live_current_value():
    ads = FakeAds()
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.before_value = {"value": 15.0, "placement": "PLACEMENT_TOP"}
    a.after_value = {"value": 30.0, "placement": "PLACEMENT_TOP"}

    result = live_client(ads).rollback(a)

    assert result == {"ok": True}
    assert ads.calls == [
        ("read_placement", "c1", "PLACEMENT_TOP"),
        ("placement", "c1", "PLACEMENT_TOP", 15.0, 15.0, False),
    ]


def test_ads_action_client_does_not_rollback_placement_without_current_value():
    ads = FakeAds()
    ads.placement_modifier = lambda campaign_id, placement: {"value": None, "placement": placement}
    a = action("set_placement_modifier", "campaign")
    a.entity_id = "c1"
    a.before_value = {"value": 15.0, "placement": "PLACEMENT_TOP"}
    a.after_value = {"value": 30.0, "placement": "PLACEMENT_TOP"}

    try:
        live_client(ads).rollback(a)
    except RuntimeError as exc:
        assert "current value is unavailable" in str(exc)
    else:
        raise AssertionError("rollback should fail closed without a live current value")


def test_campaign_pause_reads_applies_and_restores_live_state():
    ads = FakeAds()
    a = action("pause", "campaign")
    a.entity_id = "c1"
    a.before_value = {"value": "ENABLED"}
    a.after_value = {"value": "PAUSED"}
    client = live_client(ads)

    assert client.read_before_value(a) == {"value": "ENABLED"}
    assert client.apply(a) == {"ok": True}
    assert client.rollback(a) == {"ok": True}
    assert ads.calls == [
        ("read_entity_status", "campaign", "c1"),
        ("entity_status", "campaign", "c1", "PAUSED", False),
        ("entity_status", "campaign", "c1", "ENABLED", False),
    ]


def test_campaign_budget_reads_applies_and_restores_live_value():
    ads = FakeAds()
    a = action("set_budget", "campaign")
    a.entity_id = "c1"
    a.before_value = {"value": 20.0}
    a.after_value = {"value": 24.0}
    client = live_client(ads)

    assert client.read_before_value(a) == {"value": 20.0}
    assert client.apply(a) == {"ok": True}
    assert client.rollback(a) == {"ok": True}
    assert ads.calls == [
        ("read_campaign_budget", "c1"),
        ("campaign_budget", "c1", 24.0, False),
        ("campaign_budget", "c1", 20.0, False),
    ]


def test_campaign_budget_drift_blocks_write_before_apply():
    ads = FakeAds()

    def changed_budget(campaign_id):
        ads.calls.append(("read_campaign_budget", campaign_id))
        return {"value": 19.0}

    ads.campaign_budget = changed_budget
    a = action("set_budget", "campaign")
    a.entity_id = "c1"
    updated, response = apply_action(a, live_client(ads), now=dt.datetime.now(dt.timezone.utc))
    assert updated.status == sm.Status.FAILED
    assert updated.error.startswith("drift:")
    assert response is None
    assert ads.calls == [("read_campaign_budget", "c1")]


def test_ad_group_default_bid_reads_applies_and_restores_live_value():
    ads = FakeAds()
    a = action("set_bid", "ad_group")
    a.entity_id = "g1"
    a.before_value = {"value": 0.75}
    a.after_value = {"value": 0.9}
    client = live_client(ads)

    assert client.read_before_value(a) == {"value": 0.75}
    assert client.apply(a) == {"ok": True}
    assert client.rollback(a) == {"ok": True}
    assert ads.calls == [
        ("read_ad_group_bid", "g1"),
        ("ad_group_bid", "g1", 0.9, False),
        ("ad_group_bid", "g1", 0.75, False),
    ]


def test_keyword_status_reads_applies_and_restores_live_state():
    ads = FakeAds()
    a = action("pause", "keyword")
    a.before_value = {"value": "ENABLED"}
    a.after_value = {"value": "PAUSED"}
    client = live_client(ads)

    assert client.read_before_value(a) == {"value": "ENABLED"}
    assert client.apply(a) == {"ok": True}
    assert client.rollback(a) == {"ok": True}
    assert ads.calls == [
        ("read_entity_status", "keyword", "k1"),
        ("entity_status", "keyword", "k1", "PAUSED", False),
        ("entity_status", "keyword", "k1", "ENABLED", False),
    ]


@pytest.mark.parametrize(
    ("entity_type", "action_type", "before", "after"),
    [
        ("keyword", "set_bid", {"value": 1.0}, {"value": 1.2}),
        ("target", "set_bid", {"value": 0.8}, {"value": 1.0}),
        ("campaign", "set_placement_modifier", {"value": 15.0, "placement": "PLACEMENT_TOP"}, {"value": 30.0, "placement": "PLACEMENT_TOP"}),
        ("campaign", "pause", {"value": "ENABLED"}, {"value": "PAUSED"}),
        ("campaign", "enable", {"value": "PAUSED"}, {"value": "ENABLED"}),
        ("campaign", "set_budget", {"value": 20.0}, {"value": 24.0}),
        ("ad_group", "set_bid", {"value": 0.75}, {"value": 0.9}),
        ("ad_group", "pause", {"value": "ENABLED"}, {"value": "PAUSED"}),
        ("ad_group", "enable", {"value": "PAUSED"}, {"value": "ENABLED"}),
        ("keyword", "pause", {"value": "ENABLED"}, {"value": "PAUSED"}),
        ("keyword", "enable", {"value": "PAUSED"}, {"value": "ENABLED"}),
        ("target", "pause", {"value": "ENABLED"}, {"value": "PAUSED"}),
        ("target", "enable", {"value": "PAUSED"}, {"value": "ENABLED"}),
    ],
)
def test_every_reversible_live_capability_has_a_worker_rollback_route(
    entity_type, action_type, before, after
):
    assert capability(entity_type, action_type).rollback_supported
    ads = FakeAds()
    item = action(action_type, entity_type)
    item.before_value = before
    item.after_value = after

    assert live_client(ads).rollback(item) == {"ok": True}
    assert ads.calls


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
