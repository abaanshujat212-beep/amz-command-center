"""Canonical readiness values shared by backend services.

Documentation or fixture evidence is intentionally not sufficient for LIVE_READY.
The database additionally requires an evidence source and observed timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class ReadinessState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    WAITING_FOR_API_APPROVAL = "WAITING_FOR_API_APPROVAL"
    WAITING_FOR_AUTHORIZATION = "WAITING_FOR_AUTHORIZATION"
    WAITING_FOR_MARKETING_STREAM = "WAITING_FOR_MARKETING_STREAM"
    WAITING_FOR_AMC = "WAITING_FOR_AMC"
    UNSUPPORTED_MARKETPLACE = "UNSUPPORTED_MARKETPLACE"
    UNSUPPORTED_API_VERSION = "UNSUPPORTED_API_VERSION"
    LIVE_READY = "LIVE_READY"


class EvidenceKind(StrEnum):
    DOCUMENTATION = "documentation"
    FIXTURE = "fixture"
    SANDBOX = "sandbox"
    AUTHORIZED_LIVE_READ = "authorized_live_read"
    AUTHORIZED_LIVE_WRITE = "authorized_live_write"


LIVE_EVIDENCE = {
    EvidenceKind.AUTHORIZED_LIVE_READ,
    EvidenceKind.AUTHORIZED_LIVE_WRITE,
}


@dataclass(frozen=True)
class ReadinessEvidence:
    kind: EvidenceKind
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("evidence source is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("evidence timestamp must be timezone-aware")


def validated_state(
    requested: ReadinessState,
    evidence: ReadinessEvidence | None,
) -> ReadinessState:
    """Fail closed when LIVE_READY lacks authorized live evidence."""
    missing_live_evidence = evidence is None or evidence.kind not in LIVE_EVIDENCE
    if requested is ReadinessState.LIVE_READY and missing_live_evidence:
        raise ValueError("LIVE_READY requires authorized live evidence")
    if evidence and evidence.observed_at > datetime.now(timezone.utc):
        raise ValueError("evidence timestamp cannot be in the future")
    return requested
