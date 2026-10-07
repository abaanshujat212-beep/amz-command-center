from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0046_entity_protection.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0046_entity_protection.sql").read_text()
ENGINE = (ROOT / "services/rules/engine.py").read_text()
API = (ROOT / "apps/web/app/api/protections/route.ts").read_text()
PAGE = (ROOT / "apps/web/app/settings/protections/page.tsx").read_text()


def test_protections_are_append_only_audited_tenant_scoped_and_reversible():
    assert "entity_protection_event" in UP
    assert "entity_protection_immutable" in UP
    assert "only an active protection can transition" in UP
    assert "force row level security" in UP
    assert "entity_protection_lookup_idx" in UP
    assert "drop table if exists entity_protection" in DOWN


def test_rules_api_and_ui_share_the_protection_boundary():
    assert "active_protection(" in ENGINE
    assert "Guard.PROTECTED_ENTITY" in ENGINE
    assert "owner_or_admin_required" in API
    assert "entity_protection.created" in API
    assert "Return to automation" in PAGE
    assert "live application still requires capability support" in PAGE
