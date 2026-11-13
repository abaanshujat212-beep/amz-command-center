from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "apps/web/app/api/inventory/forecast/route.ts").read_text()
LIB = (ROOT / "apps/web/lib/inventory.ts").read_text()


def test_inventory_forecast_route_is_session_and_tenant_scoped():
    assert "currentContext()" in ROUTE
    assert "withTenant(actor.tenantId" in ROUTE
    assert "inventoryForecastRead" in ROUTE


def test_forecast_blocks_sparse_stale_and_unknown_inputs_with_assumptions():
    assert "where tenant_id=$1" in LIB
    assert 'minimumHistoryDays: 14' in LIB
    assert "inventory_${row.freshness_state}" in LIB
    assert "available_now_unknown" in LIB
    assert 'seasonality: "not_applied"' in LIB
    assert "daysOfSupply" in LIB
