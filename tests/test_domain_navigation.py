from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_contextual_navigation_groups_existing_domains_and_routes():
    contract = (ROOT / "apps/web/lib/domain-navigation.ts").read_text()
    for domain in ("Home", "Products", "Decisions", "Ads / PPC", "Finance", "AI"):
        assert f'label: "{domain}"' in contract
    for route in ("/opportunities", "/approvals", "/campaigns", "/economics", "/copilot"):
        assert route in contract


def test_module_visibility_uses_canonical_readiness_states():
    contract = (ROOT / "apps/web/lib/domain-navigation.ts").read_text()
    for state in ("DISABLED", "RECOMMENDED", "ENABLED", "BETA", "EXTERNAL_ACCESS_REQUIRED", "NOT_READY"):
        assert state in contract
    assert 'visibility_state === "DISABLED"' in contract


def test_navigation_does_not_add_account_selection_or_authorization_bypass():
    joined = "\n".join((ROOT / path).read_text() for path in (
        "apps/web/lib/domain-navigation.ts", "apps/web/components/sidebar-nav.tsx", "apps/web/components/mobile-nav.tsx"
    ))
    assert "active_tenant_id" not in joined
    assert "set_tenant" not in joined
    assert "tenant picker" not in joined.lower()
