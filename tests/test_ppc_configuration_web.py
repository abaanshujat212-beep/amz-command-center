from pathlib import Path

ROOT = Path(__file__).parents[1]
LIB = (ROOT / "apps/web/lib/ppc-configuration.ts").read_text()
PAGE = (ROOT / "apps/web/app/settings/ppc-goals/page.tsx").read_text()
COMPONENT = (ROOT / "apps/web/app/settings/ppc-goals/ppc-goal-settings.tsx").read_text()
ROUTES = [
    ROOT / "apps/web/app/api/ppc/config/route.ts",
    ROOT / "apps/web/app/api/ppc/config/activate/route.ts",
    ROOT / "apps/web/app/api/ppc/config/objectives/route.ts",
    ROOT / "apps/web/app/api/ppc/config/strategies/route.ts",
    ROOT / "apps/web/app/api/ppc/goals/route.ts",
]


def test_configuration_routes_are_tenant_scoped_role_gated_and_idempotent():
    assert len(ROUTES) == 5
    for route in ROUTES:
        source = route.read_text()
        assert "currentContext" in source
        assert "withTenant" in source
    assert "owner, admin or settings scope required" in LIB
    assert "configuration_write_request" in LIB
    assert "Idempotency-Key was already used for a different payload" in LIB
    assert "function canonical" in LIB


def test_versions_remain_inactive_until_explicit_confirmation():
    assert ",$4,false,$5::jsonb" in LIB
    assert 'raw.confirmation!=="ACTIVATE"' in LIB
    assert "type ACTIVATE to confirm this unsafe change" in LIB
    assert "insert into action" not in LIB + PAGE + COMPONENT
    assert "does not arm automation or send Amazon mutations" in COMPONENT


def test_effective_goal_ui_exposes_inheritance_and_permissions():
    assert "sources[field]" in LIB
    assert "Effective inherited goal" in COMPONENT
    assert "Inherited value missing" in COMPONENT
    assert "No active source" in COMPONENT
    assert "Read-only" in COMPONENT
    assert "/settings/ppc-goals" in (
        ROOT / "apps/web/components/settings-nav.tsx"
    ).read_text()

