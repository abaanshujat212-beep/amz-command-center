import datetime as dt

from services.actions import state_machine as sm
from services.actions.native_controls import NativeControlState, evaluate_native_control

NOW=dt.datetime(2026,11,23,12,tzinfo=dt.timezone.utc)

def action(action_type="set_bid",entity_type="keyword"):
    return sm.Action(id="a1",tenant_id="t1",entity_type=entity_type,entity_id="e1",action_type=action_type,before_value={"value":1},after_value={"value":1.1},status=sm.Status.APPROVED)

def state(**overrides):
    values=dict(campaign_id="c1",bidding_strategy="fixed",bidding_strategy_supported=True,budget_rule_active=False,schedule_rule_active=False,rule_based_bidding_active=False,cost_control_active=False,source_observed_at=NOW-dt.timedelta(hours=1),source_api_version="sp-campaigns-v3")
    values.update(overrides)
    return NativeControlState(**values)

def test_missing_stale_and_unknown_evidence_fail_closed():
    assert evaluate_native_control(action(),None,now=NOW).reason_code=="NATIVE_CONTROL_EVIDENCE_MISSING"
    assert evaluate_native_control(action(),state(source_observed_at=NOW-dt.timedelta(hours=25)),now=NOW).reason_code=="NATIVE_CONTROL_EVIDENCE_STALE"
    assert evaluate_native_control(action(),state(bidding_strategy="future",bidding_strategy_supported=False),now=NOW).reason_code=="NATIVE_CONTROL_UNSUPPORTED"
    assert evaluate_native_control(action(),state(source_observed_at=NOW+dt.timedelta(minutes=6)),now=NOW).reason_code=="NATIVE_CONTROL_EVIDENCE_INVALID"

def test_dynamic_strategy_blocks_bid_with_explicit_ownership_options():
    decision=evaluate_native_control(action(),state(bidding_strategy="dynamic_up_down"),now=NOW)
    assert decision.reason_code=="NATIVE_OPTIMIZATION_CONFLICT"
    assert decision.ownership_options==("keep_amazon_control","propose_separate_control_transfer")

def test_rule_controls_only_block_their_conflicting_action_class():
    assert evaluate_native_control(action("set_budget","campaign"),state(budget_rule_active=True),now=NOW).allowed is False
    assert evaluate_native_control(action("pause","campaign"),state(schedule_rule_active=True),now=NOW).allowed is False
    assert evaluate_native_control(action("set_placement_modifier","campaign"),state(cost_control_active=True),now=NOW).allowed is False
    assert evaluate_native_control(action("set_budget","campaign"),state(rule_based_bidding_active=True),now=NOW).allowed is True

def test_fixed_strategy_without_native_rules_allows_dispatch():
    assert evaluate_native_control(action(),state(),now=NOW).allowed is True

def test_unrelated_negative_action_does_not_require_native_control_evidence():
    assert evaluate_native_control(action("add_negative_exact","search_term"),None,now=NOW).allowed is True

def test_keyword_harvest_is_blocked_by_native_bid_ownership():
    assert evaluate_native_control(action("create_keyword","search_term"),state(bidding_strategy="dynamic_down_only"),now=NOW).reason_code=="NATIVE_OPTIMIZATION_CONFLICT"

def test_unknown_required_controls_block_but_unrelated_unknown_does_not():
    for field in ("rule_based_bidding_active", "cost_control_active"):
        assert evaluate_native_control(action(), state(**{field: None}), now=NOW).allowed is False
    assert evaluate_native_control(action("set_budget", "campaign"), state(budget_rule_active=None), now=NOW).allowed is False
    assert evaluate_native_control(action("pause", "campaign"), state(schedule_rule_active=None), now=NOW).allowed is False
    assert evaluate_native_control(action(), state(budget_rule_active=None), now=NOW).allowed is True
