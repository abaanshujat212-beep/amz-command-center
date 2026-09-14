from services.actions.audit import EventType, sanitize


def test_canonical_event_set_covers_execution_lifecycle():
    assert {item.value for item in EventType} == {
        "action.live_apply.requested",
        "action.live_apply.started",
        "action.live_apply.succeeded",
        "action.live_apply.failed",
        "action.live_apply.drift_blocked",
        "action.retry.scheduled",
        "action.retry.attempted",
        "action.retry.exhausted",
        "action.rollback.requested",
        "action.rollback.succeeded",
        "action.rollback.failed",
        "action.verification.scheduled",
        "action.verification.checkpoint",
        "action.verification.result",
        "action.verification.terminal",
    }


def test_audit_payload_redacts_secrets_recursively():
    result = sanitize(
        {
            "access_token": "secret",
            "nested": {"Authorization": "Bearer secret", "safe": "ok"},
            "clientSecret": "secret",
        }
    )
    assert result["access_token"] == "[REDACTED]"
    assert result["nested"]["Authorization"] == "[REDACTED]"
    assert result["nested"]["safe"] == "ok"
    assert result["clientSecret"] == "[REDACTED]"
