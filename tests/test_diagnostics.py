"""Diagnostic ('flag') rules: they must always speak, and never act.

No database needed. Every test here pairs a diagnostic with an equivalent
change proposal in the SAME context, because a bypass test that only asserts
"the flag was allowed" would still pass if check() had stopped blocking
everything. The control case is what makes the assertion mean something.
"""

from __future__ import annotations

import datetime as dt

import pytest

from services.rules import guardrails as gr
from services.rules.compiler import (
    METRICS,
    RuleValidationError,
    compile_condition,
    render_reason,
    resolve_action,
)
from services.rules.diagnostic_rules import DIAGNOSTIC_RULES
from services.rules.rule_catalog import ALL_RULES, all_rule_rows
from services.rules.starter_rules import STARTER_RULES, rule_rows

NOW = dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.timezone.utc)
SETTLED_THROUGH = NOW.date() - dt.timedelta(days=3)


def _ctx(**over) -> gr.RunContext:
    base = dict(now=NOW, data_through=SETTLED_THROUGH, data_loaded_at=NOW)
    base.update(over)
    return gr.RunContext(**base)


def _flag(**over) -> gr.Proposal:
    base = dict(
        entity_type="keyword",
        entity_id="kw-1",
        action_type="flag",
        before_value=None,
        after_value=None,
        clicks=4,
        impressions=20000,
    )
    base.update(over)
    return gr.Proposal(**base)


def _bid_change(**over) -> gr.Proposal:
    base = dict(
        entity_type="keyword",
        entity_id="kw-1",
        action_type="set_bid",
        before_value=1.00,
        after_value=1.10,
        clicks=4,
        impressions=20000,
    )
    base.update(over)
    return gr.Proposal(**base)


# --------------------------------------------------------------- action side
def test_flag_resolves_to_no_value():
    assert resolve_action({"type": "flag", "severity": "warning"}, None) is None
    # ...and does not need a current value, unlike every change action
    with pytest.raises(RuleValidationError):
        resolve_action({"type": "set_bid", "op": "multiply", "factor": 1.1}, None)


def test_flag_carrying_a_mutation_key_is_rejected():
    """A rule that looks harmless in the UI but hides a real op."""
    with pytest.raises(RuleValidationError) as exc:
        resolve_action({"type": "flag", "op": "multiply", "factor": 0.5}, 1.00)
    assert "must not carry" in str(exc.value)


def test_no_catalog_diagnostic_can_mutate():
    """The regression test for #28: a diagnostic must stay inert forever."""
    for rule in ALL_RULES:
        if rule["action"]["type"] in gr.DIAGNOSTIC_ACTIONS:
            assert resolve_action(rule["action"], 1.00) is None, rule["code"]


# ---------------------------------------------------------------- guardrails
def test_kill_switch_silences_changes_but_not_findings():
    cfg = gr.TenantGuardConfig()          # automation_enabled=False by default
    assert cfg.automation_enabled is False

    blocked = gr.check(_bid_change(), cfg, _ctx(), min_clicks=0, min_impressions=5000)
    assert blocked.allowed is False
    assert blocked.blocked_by is gr.Guard.KILL_SWITCH

    allowed = gr.check(_flag(), cfg, _ctx(), min_clicks=0, min_impressions=5000)
    assert allowed.allowed is True
    assert allowed.blocked_by is None
    assert allowed.value is None


def test_blast_radius_halts_changes_but_not_findings():
    """'30% of your keywords have terrible CTR' is a finding, not a runaway."""
    cfg = gr.TenantGuardConfig(automation_enabled=True, dry_run=True)
    ctx = _ctx(entities_evaluated=100, entities_matched=90)

    blocked = gr.check(_bid_change(), cfg, ctx, min_clicks=0, min_impressions=5000)
    assert blocked.blocked_by is gr.Guard.BLAST_RADIUS

    assert gr.check(_flag(), cfg, ctx, min_clicks=0, min_impressions=5000).allowed


def test_cooldown_and_daily_limit_do_not_apply_to_findings():
    cfg = gr.TenantGuardConfig(automation_enabled=True)
    ctx = _ctx(
        last_applied_at=NOW - dt.timedelta(days=1),
        changes_applied_today=cfg.max_changes_per_day,
    )

    blocked = gr.check(_bid_change(), cfg, ctx, min_clicks=0, min_impressions=5000)
    assert blocked.blocked_by in (gr.Guard.COOLDOWN, gr.Guard.DAILY_CHANGE_LIMIT)

    assert gr.check(_flag(), cfg, ctx, min_clicks=0, min_impressions=5000).allowed


def test_findings_still_obey_data_quality():
    """A wrong diagnosis costs trust faster than no diagnosis."""
    cfg = gr.TenantGuardConfig()

    stale = gr.check(
        _flag(),
        cfg,
        _ctx(data_loaded_at=NOW - dt.timedelta(hours=72)),
        min_clicks=0,
        min_impressions=5000,
    )
    assert stale.blocked_by is gr.Guard.STALE_DATA

    unsettled = gr.check(
        _flag(),
        cfg,
        _ctx(data_through=NOW.date()),
        min_clicks=0,
        min_impressions=5000,
    )
    assert unsettled.blocked_by is gr.Guard.UNSETTLED_DATA

    thin = gr.check(
        _flag(clicks=2, impressions=50),
        cfg,
        _ctx(),
        min_clicks=30,
        min_impressions=500,
    )
    assert thin.blocked_by is gr.Guard.THIN_DATA


# ------------------------------------------------------------------- catalog
def test_the_three_planned_diagnostics_exist():
    codes = {r["code"] for r in DIAGNOSTIC_RULES}
    assert codes == {
        "flag_low_ctr_listing",
        "flag_low_cvr_detail_page",
        "flag_above_break_even",
    }


def test_every_catalog_rule_compiles():
    for rule in ALL_RULES:
        sql, params = compile_condition(rule["condition"])
        assert "select" not in sql.lower(), rule["code"]
        assert params, rule["code"]


def test_diagnostic_reason_templates_render_without_metrics():
    """A missing metric must degrade to 'n/a', never crash a run."""
    for rule in DIAGNOSTIC_RULES:
        text = render_reason(rule["reason_template"], {})
        assert text and "{" not in text.replace("{{", ""), rule["code"]


def test_low_ctr_rule_uses_an_account_relative_threshold():
    """Absolute CTR thresholds are noise in one account and silence in another."""
    rule = next(r for r in DIAGNOSTIC_RULES if r["code"] == "flag_low_ctr_listing")
    sql, _ = compile_condition(rule["condition"])
    assert METRICS["account_ctr"] in sql
    # a click-starved keyword is the point of this rule, so clicks cannot gate it
    assert rule["min_clicks"] == 0
    assert rule["min_impressions"] >= 1000


def test_catalog_seeds_starter_and_diagnostic_rules():
    rows = all_rule_rows("11111111-1111-1111-1111-111111111111")
    assert len(rows) == len(STARTER_RULES) + len(DIAGNOSTIC_RULES)
    assert all(r["enabled"] is False and r["dry_run"] is True for r in rows)


def test_catalog_shaping_matches_starter_rules_shaping():
    """Pins the two shapers together until starter_rules.rule_rows is removed."""
    tenant = "11111111-1111-1111-1111-111111111111"
    legacy = rule_rows(tenant)
    from_catalog = [r for r in all_rule_rows(tenant) if r["code"] in {x["code"] for x in STARTER_RULES}]
    assert from_catalog == legacy
