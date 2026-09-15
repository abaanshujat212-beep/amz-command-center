"""Grounded, tenant-scoped response contract for every AI metric claim.

This module contains no model or database write tool. It validates evidence
returned by the existing read-only copilot runner before an answer reaches UI.
Workspace content is evidence data, never an instruction source.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

ALLOWED_DOMAINS = frozenset(
    {"home", "products", "decisions", "ads", "inventory", "finance", "ai", "reports"}
)
READ_ONLY_TOOLS = frozenset({"copilot.sql.read", "system_map.read"})


class GroundingError(ValueError):
    """A response cannot safely be represented as grounded."""


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    PARTIAL = "partial"
    MISSING = "missing"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ContextEnvelope:
    tenant_id: str
    domain: str
    marketplace_id: str | None = None
    advertising_profile_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise GroundingError("tenant context is required")
        if self.domain not in ALLOWED_DOMAINS:
            raise GroundingError(f"domain {self.domain!r} is not allowed")


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    provider: str
    observed_at: dt.datetime
    data_through: dt.date | None
    freshness: Freshness
    completeness: float
    show_data_url: str
    scope: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.provider or not self.scope:
            raise GroundingError("source id, provider and scope are required")
        if self.observed_at.tzinfo is None:
            raise GroundingError("source observed_at must include a timezone")
        if not 0 <= self.completeness <= 1:
            raise GroundingError("source completeness must be between 0 and 1")
        if not self.show_data_url.startswith("/") or self.show_data_url.startswith("//"):
            raise GroundingError("show-data links must be internal tenant-scoped routes")


@dataclass(frozen=True)
class MetricClaim:
    key: str
    value: int | float | None
    unit: str
    source_ids: tuple[str, ...]
    as_of: dt.date | None

    def __post_init__(self) -> None:
        if not self.key or not self.unit:
            raise GroundingError("metric key and unit are required")
        if not self.source_ids:
            raise GroundingError(f"numeric claim {self.key!r} has no source")


@dataclass(frozen=True)
class GroundedResponse:
    context: ContextEnvelope
    narrative: str
    sources: tuple[SourceReference, ...]
    claims: tuple[MetricClaim, ...] = ()
    disclosures: tuple[str, ...] = ()
    refusal_reason: str | None = None
    tools_used: tuple[str, ...] = ()


def validate(response: GroundedResponse) -> GroundedResponse:
    """Fail closed on ungrounded claims, hidden staleness or write-capable tools."""
    if any(tool not in READ_ONLY_TOOLS for tool in response.tools_used):
        raise GroundingError("AI responses may use read-only allowlisted tools only")
    source_by_id = {source.source_id: source for source in response.sources}
    if len(source_by_id) != len(response.sources):
        raise GroundingError("source ids must be unique")
    for claim in response.claims:
        unknown = sorted(set(claim.source_ids).difference(source_by_id))
        if unknown:
            raise GroundingError(f"claim {claim.key!r} cites unknown sources: {unknown}")
    risky = any(
        source.freshness != Freshness.FRESH or source.completeness < 1
        for source in response.sources
    )
    if risky and not response.disclosures:
        raise GroundingError("stale, partial, missing or blocked evidence must be disclosed")
    if response.claims and not response.sources:
        raise GroundingError("metric claims require evidence sources")
    if response.refusal_reason and response.claims:
        raise GroundingError("a refused response cannot also assert metric claims")
    return response


def refusal(context: ContextEnvelope, reason: str) -> GroundedResponse:
    if not reason.strip():
        raise GroundingError("refusal reason is required")
    return GroundedResponse(context=context, narrative=reason, sources=(), refusal_reason=reason)
