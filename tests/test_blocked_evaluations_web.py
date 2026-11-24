from pathlib import Path

ROOT = Path(__file__).parents[1]
LIB = (ROOT / "apps/web/lib/blocked-evaluations.ts").read_text()
PAGE = (ROOT / "apps/web/app/recommendations/blocked/page.tsx").read_text()
LIST = (ROOT / "apps/web/app/recommendations/page.tsx").read_text()


def test_panel_is_tenant_scoped_bounded_and_not_an_approval_queue():
    assert "withTenant(tenantId" in PAGE
    assert "currentTenantId()" in PAGE
    assert "where e.tenant_id=$1 and e.matched is true" in LIB
    assert "nullif(btrim(e.blocked_by),'') is not null" in LIB
    assert "limit $2" in LIB
    assert "not queued for approval" in PAGE
    assert "action={" not in PAGE
    assert 'href="/recommendations/blocked"' in LIST


def test_sql_projection_never_loads_private_fields():
    projection = LIB.split("select e.id::text")[1].split("from rule_evaluation")[0]
    for private_field in ("entity_id","metrics_snapshot","reason_text","proposed_action"):
        assert private_field not in projection
    assert "blockedEvaluationReason(row.blocked_by)" in LIB
