import datetime as dt

import pytest

from services.copilot.grounding import (
    ContextEnvelope,
    Freshness,
    GroundedResponse,
    GroundingError,
    MetricClaim,
    SourceReference,
    refusal,
    validate,
)

NOW = dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc)


def context() -> ContextEnvelope:
    return ContextEnvelope("tenant-a", "ads", "A1F83G8C2ARO7P", "profile-1")


def source(*, freshness=Freshness.FRESH, completeness=1.0) -> SourceReference:
    return SourceReference(
        "ads-campaign-daily:2026-09-12",
        "amazon_ads_api",
        NOW,
        dt.date(2026, 9, 12),
        freshness,
        completeness,
        "/campaigns?through=2026-09-12",
        "tenant:tenant-a/marketplace:A1F83G8C2ARO7P",
    )


def claim() -> MetricClaim:
    return MetricClaim("spend", 123.45, "GBP", ("ads-campaign-daily:2026-09-12",), dt.date(2026, 9, 12))


def test_grounded_metric_preserves_context_source_date_freshness_and_link():
    result = validate(GroundedResponse(context(), "Spend was GBP 123.45.", (source(),), (claim(),), tools_used=("copilot.sql.read",)))
    assert result.context.tenant_id == "tenant-a"
    assert result.sources[0].provider == "amazon_ads_api"
    assert result.sources[0].show_data_url.startswith("/campaigns")


def test_numeric_claim_without_source_fails_closed():
    with pytest.raises(GroundingError, match="no source"):
        MetricClaim("acos", 0.3, "ratio", (), dt.date(2026, 9, 12))


def test_unknown_source_reference_fails_closed():
    bad = MetricClaim("spend", 2, "GBP", ("invented",), dt.date(2026, 9, 12))
    with pytest.raises(GroundingError, match="unknown sources"):
        validate(GroundedResponse(context(), "claim", (source(),), (bad,)))


@pytest.mark.parametrize("state", [Freshness.STALE, Freshness.PARTIAL, Freshness.MISSING, Freshness.BLOCKED])
def test_nonfresh_evidence_requires_visible_disclosure(state):
    with pytest.raises(GroundingError, match="must be disclosed"):
        validate(GroundedResponse(context(), "claim", (source(freshness=state),), (claim(),)))


def test_incomplete_evidence_requires_visible_disclosure():
    result = validate(GroundedResponse(context(), "partial", (source(completeness=0.5),), (claim(),), ("Only 50% of expected rows are available.",)))
    assert result.disclosures


def test_write_capable_or_unknown_tool_is_refused():
    with pytest.raises(GroundingError, match="read-only"):
        validate(GroundedResponse(context(), "no", (), tools_used=("amazon.apply",)))


def test_context_is_tenant_scoped_and_domain_allowlisted():
    with pytest.raises(GroundingError):
        ContextEnvelope("", "ads")
    with pytest.raises(GroundingError):
        ContextEnvelope("tenant-a", "unknown")


def test_refusal_contains_no_metric_claims():
    response = refusal(context(), "Inventory evidence is blocked until an approved source is available.")
    assert response.refusal_reason and not response.claims
