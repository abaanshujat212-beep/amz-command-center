import pytest

from packages.shared.action_capabilities import (
    ActionCapability,
    assert_worker_capability,
    capability,
    live_ready,
    required_confirmation,
)


def test_unknown_capability_is_false_by_default():
    assert capability("campaign", "delete") == ActionCapability()


def test_keyword_harvest_is_approval_gated_and_explicitly_non_reversible():
    item = capability("search_term", "create_keyword")
    assert item.recommendation_supported
    assert item.approval_supported
    assert item.live_baseline_read_supported
    assert item.live_apply_supported
    assert not item.rollback_supported
    assert required_confirmation("search_term", "create_keyword") == "CREATE KEYWORD"


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


def test_placement_rollback_requires_authorized_live_evidence():
    assert_worker_capability(
        "campaign",
        "set_placement_modifier",
        phase="rollback",
        readiness_state="LIVE_READY",
        verification_level="AUTHORIZED_LIVE_WRITE",
    )
    with pytest.raises(RuntimeError, match="not LIVE_READY"):
        assert_worker_capability(
            "campaign",
            "set_placement_modifier",
            phase="rollback",
            readiness_state="LIVE_READY",
            verification_level="STATIC_CONTRACT",
        )
