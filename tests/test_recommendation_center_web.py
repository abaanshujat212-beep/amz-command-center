from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_recommendation_center_uses_tenant_safe_queries_and_existing_approval_path():
    listing = (ROOT / "apps/web/app/recommendations/page.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "apps/web/app/recommendations/[id]/page.tsx").read_text(encoding="utf-8")
    assert "withTenant" in listing and "currentTenantId" in listing
    assert "listRecommendations" in listing and "parseRecommendationFilters" in listing
    assert 'from "@/app/approvals/actions"' in detail
    assert "approveAction" in detail and "rejectAction" in detail
    assert "/api/" not in detail


def test_recommendation_center_surfaces_operator_evidence_and_safety():
    detail = (ROOT / "apps/web/app/recommendations/[id]/page.tsx").read_text(encoding="utf-8")
    for text in ("Current value", "Proposed value", "Goals and objective", "Economics", "Expected behavior", "Conflicts and dependencies", "Evidence", "Unsupported for live application"):
        assert text in detail
    assert "live_baseline_read_supported" in detail
    assert "rollback_supported" in detail
    assert "verification_supported" in detail


def test_recommendations_are_discoverable_in_decisions_navigation():
    navigation = (ROOT / "apps/web/lib/domain-navigation.ts").read_text(encoding="utf-8")
    assert '{ href: "/recommendations", label: "Recommendations" }' in navigation
