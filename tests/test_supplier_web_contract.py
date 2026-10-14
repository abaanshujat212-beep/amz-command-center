from pathlib import Path

ROOT=Path(__file__).parents[1]


def test_supplier_workspace_is_discoverable_and_tenant_scoped():
    nav=(ROOT/"apps/web/lib/domain-navigation.ts").read_text()
    page=(ROOT/"apps/web/app/suppliers/page.tsx").read_text()
    lib=(ROOT/"apps/web/lib/suppliers.ts").read_text()
    assert '/suppliers' in nav
    assert "withTenant" in page and "listSupplierWorkspace" in page
    assert "where s.tenant_id=$1" in lib
    assert "supplier:documents" in lib


def test_supplier_writes_are_role_gated_audited_and_api_exposed():
    lib=(ROOT/"apps/web/lib/suppliers.ts").read_text()
    routes=list((ROOT/"apps/web/app/api/suppliers").rglob("route.ts"))
    assert "SupplierInputError" in lib and "supplier.quote_versioned" in lib
    assert "only owners or admins can register supplier documents" in lib
    assert len(routes) == 4
