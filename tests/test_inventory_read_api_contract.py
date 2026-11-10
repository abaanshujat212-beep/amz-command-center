from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "apps/web/app/api/inventory/route.ts").read_text()
LIB = (ROOT / "apps/web/lib/inventory.ts").read_text()


def test_inventory_read_route_uses_authenticated_tenant_and_tenant_transaction():
    assert "currentContext()" in ROUTE
    assert "withTenant(actor.tenantId" in ROUTE
    assert "inventorySnapshotRead" in ROUTE
    assert "pageSize" in ROUTE and "freshHours" in ROUTE


def test_inventory_read_returns_latest_source_attributed_position_with_freshness():
    assert "distinct on (s.location_id,s.sku)" in LIB
    assert "s.tenant_id=$1" in LIB
    assert "s.observed_at < now()" in LIB
    assert "s.freshness_state <> 'current'" in LIB
    assert "unknown: 0" in LIB
    assert "availableQty" in LIB and "inboundQty" in LIB and "expectedAvailableAt" in LIB
