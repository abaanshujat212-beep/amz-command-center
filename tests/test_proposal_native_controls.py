import datetime as dt

import pytest

from services.rules.native_controls import evaluate_proposed_native_control
from services.rules.query import build_candidate_sql

NOW = dt.datetime(2026, 11, 23, tzinfo=dt.timezone.utc)
SAFE = {
    "campaign_id": "campaign",
    "bidding_strategy": "fixed",
    "bidding_strategy_supported": True,
    "budget_rule_active": False,
    "schedule_rule_active": False,
    "rule_based_bidding_active": False,
    "cost_control_active": False,
    "source_observed_at": NOW,
    "source_api_version": "v3",
}


class Cursor:
    def __init__(self, record):
        self.record = record
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.record


def decision(cur, *, kind="set_bid", entity="keyword", key="keyword", **kwargs):
    return evaluate_proposed_native_control(
        cur, tenant_id="tenant", action_type=kind, entity_type=entity, entity_id=key,
        before_value=None, after_value=kwargs.get("after", {}),
        metrics_snapshot=kwargs.get("metrics", {"campaign_id": "campaign"}), now=NOW,
    )


@pytest.mark.parametrize(("change", "code"), [
    ({}, None),
    ({"source_observed_at": NOW - dt.timedelta(hours=25)}, "NATIVE_CONTROL_EVIDENCE_STALE"),
    ({"source_observed_at": NOW + dt.timedelta(minutes=6)}, "NATIVE_CONTROL_EVIDENCE_INVALID"),
    ({"rule_based_bidding_active": None}, "NATIVE_CONTROL_EVIDENCE_MISSING"),
    ({"bidding_strategy_supported": False}, "NATIVE_CONTROL_UNSUPPORTED"),
    ({"bidding_strategy": "dynamic_down_only"}, "NATIVE_OPTIMIZATION_CONFLICT"),
    ({"rule_based_bidding_active": True}, "NATIVE_OPTIMIZATION_CONFLICT"),
    ({"cost_control_active": True}, "NATIVE_OPTIMIZATION_CONFLICT"),
])
def test_bid_checks_tenant_campaign_and_canonical_state(change, code):
    cur = Cursor(SAFE | change)
    result = decision(cur)
    assert result.reason_code == code
    assert result.allowed == (code is None)
    assert cur.calls[0][1] == ("tenant", "campaign")
    assert "tenant_id = %s and campaign_id = %s" in cur.calls[0][0]
    assert "source_observed_at desc, loaded_at desc" in cur.calls[0][0]
    if code == "NATIVE_OPTIMIZATION_CONFLICT":
        assert result.ownership_options == (
            "keep_amazon_control", "propose_separate_control_transfer",
        )


@pytest.mark.parametrize(("kind", "knob"), [
    ("set_budget", "budget_rule_active"),
    ("pause", "schedule_rule_active"),
    ("enable", "schedule_rule_active"),
    ("set_placement_modifier", "cost_control_active"),
])
def test_campaign_actions_use_exact_entity_and_relevant_native_knob(kind, knob):
    cur = Cursor(SAFE | {knob: True})
    result = decision(cur, kind=kind, entity="campaign", key="exact", metrics={"campaign_id": "other"})
    assert result.reason_code == "NATIVE_OPTIMIZATION_CONFLICT"
    assert cur.calls[0][1] == ("tenant", "exact")


def test_harvest_uses_destination_only_and_missing_snapshot_or_lineage_blocks():
    cur = Cursor(None)
    result = decision(cur, kind="create_keyword", entity="search_term",
                      after={"destination": {"campaign_id": "dest"}})
    assert cur.calls[0][1] == ("tenant", "dest")
    assert result.reason_code == "NATIVE_CONTROL_EVIDENCE_MISSING"
    cur = Cursor(SAFE)
    assert not decision(cur, kind="create_keyword", entity="search_term", after={}).allowed
    assert not decision(cur, metrics={}).allowed
    assert not cur.calls


def test_unrelated_proposal_does_not_fetch_native_state():
    cur = Cursor(None)
    assert decision(cur, kind="flag").allowed
    assert decision(cur, kind="add_negative_exact", entity="search_term").allowed
    assert not cur.calls


def test_keyword_mart_only_supplies_unambiguous_complete_campaign_lineage():
    sql = build_candidate_sql("keyword", "true")
    assert "count(*) = count(nullif(btrim(campaign_id::text), ''))" in sql
    assert "count(distinct campaign_id) = 1" in sql
