from datetime import datetime, timedelta, timezone

import pytest

from packages.shared.readiness import (
    EvidenceKind,
    ReadinessEvidence,
    ReadinessState,
    validated_state,
)


def evidence(kind: EvidenceKind) -> ReadinessEvidence:
    return ReadinessEvidence(
        kind=kind,
        observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        source="test",
    )


def test_non_live_states_do_not_require_evidence():
    assert (
        validated_state(ReadinessState.NOT_CONFIGURED, None)
        is ReadinessState.NOT_CONFIGURED
    )


@pytest.mark.parametrize(
    "kind",
    [EvidenceKind.DOCUMENTATION, EvidenceKind.FIXTURE, EvidenceKind.SANDBOX],
)
def test_non_live_evidence_cannot_mark_live_ready(kind):
    with pytest.raises(ValueError, match="authorized live evidence"):
        validated_state(ReadinessState.LIVE_READY, evidence(kind))


@pytest.mark.parametrize(
    "kind",
    [EvidenceKind.AUTHORIZED_LIVE_READ, EvidenceKind.AUTHORIZED_LIVE_WRITE],
)
def test_authorized_live_evidence_can_mark_live_ready(kind):
    assert (
        validated_state(ReadinessState.LIVE_READY, evidence(kind))
        is ReadinessState.LIVE_READY
    )


def test_naive_or_future_evidence_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        ReadinessEvidence(EvidenceKind.FIXTURE, datetime.now(), "x")
    future = ReadinessEvidence(
        EvidenceKind.AUTHORIZED_LIVE_READ,
        datetime.now(timezone.utc) + timedelta(minutes=1),
        "x",
    )
    with pytest.raises(ValueError, match="future"):
        validated_state(ReadinessState.LIVE_READY, future)
