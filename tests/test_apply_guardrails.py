import datetime as dt

import pytest

from services.actions import state_machine as sm
from services.actions.apply_guardrails import ApplyGuardrailError, validate_apply_guardrails
from services.rules.guardrails import TenantGuardConfig

NOW = dt.datetime(2026, 9, 15, 8, 0, tzinfo=dt.timezone.utc)


class Cursor:
    def __init__(self, row):
        self.row = row
        self.params = None
        self.query = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row


def action(action_type="set_bid", before=1.0, after=1.1):
    return sm.Action(
        id="A1",
        tenant_id="T1",
        entity_type="keyword",
        entity_id="K1",
        action_type=action_type,
        before_value={"value": before},
        after_value={"value": after},
        status=sm.Status.APPROVED,
    )


def evidence(**overrides):
    row = {
        "data_through": dt.date(2026, 9, 12),
        "applied_today": 0,
        "budget_delta_today": 0,
        "last_applied_at": None,
        "metrics_snapshot": {
            "clicks": 40,
            "impressions": 2000,
            "break_even_acos": 0.3,
            "guardrail_context": {
                "version": 1,
                "entities_evaluated": 10,
                "entities_matched": 2,
                "min_clicks": 15,
                "min_impressions": 500,
                "source_freshness": {
                    "state": "fresh",
                    "data_loaded_at": "2026-09-15T07:00:00+00:00",
                },
            },
        },
    }
    row.update(overrides)
    return row


def enabled(**overrides):
    values = {"automation_enabled": True, "dry_run": False}
    values.update(overrides)
    return TenantGuardConfig(**values)


def test_valid_action_reuses_tenant_scoped_evidence_without_changing_target():
    cursor = Cursor(evidence())
    result = validate_apply_guardrails(cursor, action(), enabled(), now=NOW)
    assert result.budget_increase == 0
    assert cursor.params == ("T1", "A1")
    assert "e.tenant_id = a.tenant_id" in cursor.query


@pytest.mark.parametrize(
    "row",
    [
        None,
        evidence(metrics_snapshot={}),
        evidence(metrics_snapshot={"guardrail_context": {"version": 99}}),
    ],
)
def test_missing_or_unsupported_evidence_fails_closed(row):
    with pytest.raises(ApplyGuardrailError):
        validate_apply_guardrails(Cursor(row), action(), enabled(), now=NOW)


def test_stale_data_fails_closed():
    row = evidence()
    row["metrics_snapshot"]["guardrail_context"]["source_freshness"]["data_loaded_at"] = (
        "2026-09-10T00:00:00+00:00"
    )
    with pytest.raises(ApplyGuardrailError, match="stale_data"):
        validate_apply_guardrails(Cursor(row), action(), enabled(), now=NOW)


def test_current_bounds_never_silently_change_approved_target():
    with pytest.raises(ApplyGuardrailError, match="change the approved target"):
        validate_apply_guardrails(
            Cursor(evidence()), action(after=1.5), enabled(max_change_pct=0.1), now=NOW
        )


def test_current_cooldown_blocks_action():
    row = evidence(last_applied_at=NOW - dt.timedelta(days=1))
    with pytest.raises(ApplyGuardrailError, match="cooldown"):
        validate_apply_guardrails(Cursor(row), action(), enabled(cooldown_days=3), now=NOW)


def test_current_daily_change_limit_includes_projected_batch():
    with pytest.raises(ApplyGuardrailError, match="daily_change_limit"):
        validate_apply_guardrails(
            Cursor(evidence(applied_today=49)),
            action(),
            enabled(max_changes_per_day=50),
            now=NOW,
            projected_changes=1,
        )


def test_blast_radius_uses_persisted_denominator():
    row = evidence()
    row["metrics_snapshot"]["guardrail_context"].update(
        {"entities_evaluated": 20, "entities_matched": 8}
    )
    with pytest.raises(ApplyGuardrailError, match="blast_radius"):
        validate_apply_guardrails(Cursor(row), action(), enabled(blast_radius_pct=0.3), now=NOW)


def test_budget_increase_uses_current_daily_cap():
    with pytest.raises(ApplyGuardrailError, match="daily_budget_limit"):
        validate_apply_guardrails(
            Cursor(evidence(budget_delta_today=49)),
            action(action_type="set_budget", before=10, after=12),
            enabled(max_budget_increase_per_day=50),
            now=NOW,
        )
