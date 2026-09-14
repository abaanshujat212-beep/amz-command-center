import pytest

from packages.shared.action_capabilities import (
    ActionCapability,
    assert_worker_capability,
    capability,
    live_ready,
)


def test_unknown_capability_is_false_by_default():
    assert capability("campaign", "delete") == ActionCapability()


def test_local_diagnostic_is_recommendation_only():
    item = capability("search_term", "flag")
    assert item.recommendation_supported
    assert item.local_only
    assert not item.approval_supported
    assert not item.live_apply_supported


@pytest.mark.parametrize(
    "evidence",
    [None, "STATIC_CONTRACT", "DOCUMENTATION", "FIXTURE", "SANDBOX"],
)
def test_non_live_evidence_never_produces_live_ready(evidence):
    assert not live_ready("LIVE_READY", evidence)


def test_worker_requires_both_supported_phase_and_authorized_readiness():
    with pytest.raises(RuntimeError, match="not LIVE_READY"):
        assert_worker_capability(
            "keyword",
            "set_bid",
            phase="apply",
            readiness_state="LIVE_READY",
            verification_level="STATIC_CONTRACT",
        )
    assert_worker_capability(
        "keyword",
        "set_bid",
        phase="apply",
        readiness_state="LIVE_READY",
        verification_level="AUTHORIZED_LIVE_WRITE",
    )


def test_incomplete_rollback_fails_closed():
    with pytest.raises(RuntimeError, match="unsupported capability"):
        assert_worker_capability(
            "campaign",
            "set_placement_modifier",
            phase="rollback",
            readiness_state="LIVE_READY",
            verification_level="AUTHORIZED_LIVE_WRITE",
        )
