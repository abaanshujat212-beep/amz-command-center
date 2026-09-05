"""Regression checks for authenticated tenant RBAC."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "packages/db/migrations/0017_auth_rbac.sql").read_text()
SESSION = (ROOT / "apps/web/lib/session.ts").read_text()
ACTIONS = (ROOT / "apps/web/app/approvals/actions.ts").read_text()
PROXY = (ROOT / "apps/web/proxy.ts").read_text()
CLIENT_SETTINGS = (ROOT / "apps/web/app/settings/client/actions.ts").read_text()


def test_auth_schema_is_private_and_tenant_owner_is_unique():
    assert "revoke all on schema auth from public" in MIGRATION.lower()
    assert "tenant_member_one_owner" in MIGRATION
    assert "where role = 'owner'" in MIGRATION


def test_new_user_role_is_supported_without_removing_legacy_roles():
    for role in ("owner", "admin", "user", "analyst", "viewer"):
        assert f"'{role}'" in MIGRATION


def test_session_tenant_is_verified_against_rls_membership():
    assert "assertMembership(tenantId, session.user.id)" in SESSION
    assert "DEV_TENANT_ID" not in SESSION


def test_approval_authority_comes_from_authenticated_role():
    assert 'role !== "owner" && role !== "admin"' in ACTIONS
    assert "DEV_OPERATOR_USER_ID" not in ACTIONS


def test_proxy_keeps_auth_and_tenant_selection_public_only():
    assert 'pathname.startsWith("/api/auth/")' in PROXY
    assert 'pathname === "/api/tenant/select"' in PROXY
    assert 'pathname.startsWith("/api/")' in PROXY


def test_client_customisation_is_tenant_scoped_and_audited():
    assert "currentContext()" in CLIENT_SETTINGS
    assert "mayManageTenant(actor.role)" in CLIENT_SETTINGS
    assert "withTenant(actor.tenantId" in CLIENT_SETTINGS
    assert "tenant.settings_updated" in CLIENT_SETTINGS
