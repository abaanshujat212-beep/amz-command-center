from pathlib import Path

ROOT = Path(__file__).parents[1]
AUTH = (ROOT / "apps/web/lib/auth.ts").read_text()
SESSION = (ROOT / "apps/web/lib/session.ts").read_text()
ROUTE = (ROOT / "apps/web/app/api/tenant/select/route.ts").read_text()
CONTEXT = (ROOT / "apps/web/lib/business-context.ts").read_text()


def test_every_session_context_field_is_mapped_and_persisted():
    for field in ("activeWorkspaceId", "activeBrandId", "activeChannelAccountId", "activeMarketplaceContextId", "activeAdsProfileId"):
        assert field in AUTH
        assert field in SESSION
    for column in ("active_workspace_id", "active_brand_id", "active_channel_account_id", "active_marketplace_context_id", "active_ads_profile_id"):
        assert column in ROUTE


def test_switch_and_request_revalidate_all_authorities():
    assert "assertMembership(tenantId, session.user.id)" in ROUTE
    assert "assertWorkspaceOperation" in ROUTE and "assertWorkspaceOperation" in SESSION
    assert "assertBusinessHierarchy" in ROUTE and "assertBusinessHierarchy" in SESSION
    assert "withTenant(tenantId" in CONTEXT
    assert "session_workspace_tenant_authorization" in CONTEXT


def test_context_chain_and_return_route_fail_closed():
    assert "brand context is required" in CONTEXT
    assert "channel account context is required" in CONTEXT
    assert "marketplace context is required" in CONTEXT
    assert '!value.startsWith("//")' in CONTEXT
