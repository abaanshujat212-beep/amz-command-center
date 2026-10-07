import datetime as dt

from services.rules.guardrails import TenantGuardConfig
from services.rules.isolation_revive import (
    ALREADY_NEGATIVE,
    BID_UNKNOWN,
    BLOCKED,
    BOUNDS,
    COOLDOWN,
    DESTINATION_INACTIVE,
    DESTINATION_MISSING,
    DESTINATION_NO_TRAFFIC,
    DUPLICATE,
    ECONOMICS_UNKNOWN,
    POOR_HISTORY,
    PROTECTED,
    RECENT_TRAFFIC,
    RECOMMENDED,
    SAME_AD_GROUP,
    SOURCE_NO_TRAFFIC,
    THIN_HISTORY,
    UNSUPPORTED_MATCH_TYPE,
    decide_isolation,
    decide_revive,
)

NOW = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
CFG = TenantGuardConfig(min_bid=0.10, max_bid=1.00, cooldown_days=3)

LINEAGE = {
    "id": "L1", "action_id": "A1", "route_code": "generic_exact",
    "normalized_term": "hook and loop tape", "applied_at": NOW - dt.timedelta(days=10),
    "source_campaign_id": "C-AUTO", "source_ad_group_id": "G-AUTO",
    "destination_campaign_id": "C-EXACT", "destination_ad_group_id": "G-EXACT",
    "destination_match_type": "exact",
}
LIVE = {"keyword_id": "K1", "status": "ENABLED", "impressions": 400, "clicks": 12,
        "cost": 6, "orders": 2}
SOURCE = {"clicks": 9, "cost": 4, "orders": 0, "already_negative": False}


def _iso(lineage=None, *, destination=LIVE, source=SOURCE, protection_id=None,
         pending_negative=None, seen=None):
    return decide_isolation(
        {**LINEAGE, **(lineage or {})},
        destination=destination,
        source=source,
        protection_id=protection_id,
        pending_negative=pending_negative,
        seen=set() if seen is None else seen,
    )


def test_isolation_recommends_source_negative_with_lineage_evidence():
    f = _iso()
    assert (f.decision, f.blocked_reason) == (RECOMMENDED, None)
    assert (f.campaign_id, f.ad_group_id, f.match_type) == ("C-AUTO", "G-AUTO", "negative_exact")
    assert f.lineage_id == "L1"
    assert f.evidence["lineage"]["destination_ad_group_id"] == "G-EXACT"
    assert f.evidence["destination"]["clicks"] == 12
    assert f.evidence["source_since_applied"]["clicks"] == 9


def test_isolation_waits_for_a_proven_destination():
    assert _iso(destination=None).blocked_reason == DESTINATION_MISSING
    assert _iso(destination={**LIVE, "status": "paused"}).blocked_reason == DESTINATION_INACTIVE
    for thin in ({"impressions": 99}, {"clicks": 4}, {"impressions": 0, "clicks": 0}):
        assert _iso(destination={**LIVE, **thin}).blocked_reason == DESTINATION_NO_TRAFFIC


def test_isolation_avoids_overblocking_and_duplicates():
    assert _iso(source={**SOURCE, "clicks": 0}).blocked_reason == SOURCE_NO_TRAFFIC
    assert _iso(source={**SOURCE, "already_negative": True}).blocked_reason == ALREADY_NEGATIVE
    assert _iso({"destination_ad_group_id": "G-AUTO"}).blocked_reason == SAME_AD_GROUP
    assert _iso({"destination_match_type": "product"}).blocked_reason == UNSUPPORTED_MATCH_TYPE
    assert _iso(pending_negative="A9").blocked_reason == DUPLICATE
    protected = _iso(protection_id="P1")
    assert (protected.blocked_reason, protected.protection_id) == (PROTECTED, "P1")

    seen: set[str] = set()
    first, second = _iso(seen=seen), _iso({"id": "L2"}, seen=seen)
    assert first.decision == RECOMMENDED and first.subject_key.endswith("|L1")
    assert (second.decision, second.blocked_reason) == (BLOCKED, DUPLICATE)


# 50 clicks, 5 orders, ACoS 12.5% vs 30% break-even -> break-even CPC 1.20
WINNER = {
    "keyword_id": "K-WIN", "campaign_id": "C1", "ad_group_id": "G1",
    "keyword_text": "Blue  Tape", "match_type": "EXACT", "keyword_status": "paused",
    "clicks": 50, "orders": 5, "cost": 25, "sales": 200, "break_even_acos": 0.30,
    "last_bid": 0.80, "last_click_date": dt.date(2026, 8, 20), "recent_clicks": 0,
}


def _rev(kw=None, *, siblings=(), open_action=None, last_applied_at=None, cfg=CFG):
    return decide_revive(
        {**WINNER, **(kw or {})},
        enabled_siblings=siblings,
        open_action=open_action,
        last_applied_at=last_applied_at,
        cfg=cfg,
        now=NOW,
    )


def test_revive_historical_winner_at_last_bid():
    f = _rev()
    assert (f.decision, f.proposed_bid, f.current_bid) == (RECOMMENDED, 0.80, 0.80)
    assert (f.term, f.match_type, f.keyword_id) == ("blue tape", "exact", "K-WIN")
    assert f.evidence["break_even_cpc"] == 1.2
    assert f.evidence["history"]["acos"] == 0.125


def test_revive_bid_respects_break_even_cpc_and_bounds():
    assert _rev({"last_bid": 3.00}).proposed_bid == 1.00          # max_bid
    assert _rev({"last_bid": 3.00}, cfg=TenantGuardConfig(max_bid=5.0)).proposed_bid == 1.2
    # break-even CPC 4 * 0.02 = 0.08 < min_bid 0.10
    assert _rev({"break_even_acos": 0.02, "cost": 0.4}).blocked_reason == BOUNDS
    assert _rev({"last_bid": None}).blocked_reason == BID_UNKNOWN


def test_revive_excludes_poor_thin_and_unknown_history():
    assert _rev({"orders": 0, "sales": 0}).blocked_reason == POOR_HISTORY
    assert _rev({"orders": 2}).blocked_reason == POOR_HISTORY
    assert _rev({"cost": 80}).blocked_reason == POOR_HISTORY      # ACoS 40% > 30%
    assert _rev({"clicks": 19}).blocked_reason == THIN_HISTORY
    assert _rev({"break_even_acos": None}).blocked_reason == ECONOMICS_UNKNOWN


def test_revive_respects_cooldown_dormancy_and_duplicates():
    assert _rev(last_applied_at=NOW - dt.timedelta(days=1)).blocked_reason == COOLDOWN
    assert _rev(last_applied_at=NOW - dt.timedelta(days=3)).decision == RECOMMENDED
    assert _rev({"recent_clicks": 2}).blocked_reason == RECENT_TRAFFIC
    dup = _rev(siblings=["K-2"])
    assert dup.blocked_reason == DUPLICATE and dup.proposed_bid is None
    assert _rev(open_action="A1").blocked_reason == DUPLICATE
