from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0053_contextual_ai_decision_trace.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0053_contextual_ai_decision_trace.sql").read_text()
SERVICE = (ROOT / "apps/web/lib/decision-trace.ts").read_text()
EXPLAIN = (ROOT / "apps/web/app/api/copilot/explain/route.ts").read_text()
FEEDBACK = (ROOT / "apps/web/app/api/copilot/feedback/route.ts").read_text()
UI = (ROOT / "apps/web/app/copilot/decision-trace.tsx").read_text()


def test_trace_and_feedback_storage_is_append_only_and_tenant_scoped():
    assert "force row level security" in UP
    assert "copilot_decision_explanation_immutable" in UP
    assert "copilot_feedback_proposal_immutable" in UP
    assert "status = 'pending_review'" in UP
    assert "drop table if exists copilot_feedback_proposal" in DOWN


def test_explanations_only_use_persisted_evidence():
    assert "rule_evaluation" in SERVICE
    assert "action_execution_event" in SERVICE
    assert "immutable stored event" in SERVICE
    assert "LLM" not in SERVICE and "fetch(" not in SERVICE
    assert "does not infer an unstored cause" in SERVICE


def test_context_and_permissions_are_enforced_server_side():
    assert "currentContext" in EXPLAIN and "withTenant" in EXPLAIN
    assert "requireCopilotScope" in SERVICE
    assert 'includes("copilot")' in SERVICE
    assert "where a.tenant_id=$1 and a.id=$2" in SERVICE


def test_feedback_cannot_mutate_action_settings_or_amazon():
    combined = SERVICE + FEEDBACK
    assert "copilot_feedback_proposal" in combined
    assert "pending_review" in UP
    assert "insert into action" not in combined
    assert "update action" not in combined
    assert "configuration_" not in FEEDBACK
    assert "amazon" not in FEEDBACK.lower()


def test_ui_discloses_evidence_and_no_write_feedback_boundary():
    assert "Decision Trace" in UI
    assert "Source content is treated as data, never as instructions" in UI
    assert "cannot change this decision, settings, an action, or Amazon" in UI
    assert "evidence" in UI
