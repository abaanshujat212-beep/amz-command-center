import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL=os.environ.get("DATABASE_URL","postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL=os.environ.get("DATABASE_URL_APP","postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_supplier_quotes_are_versioned_and_documents_are_scope_protected():
    tenant=uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("insert into tenant(id,name,slug) values(%s,'Supplier test',%s)",(tenant,str(tenant)))
        party=admin.execute("insert into party(tenant_id,party_kind,display_name,normalized_name) values(%s,'organization','Factory','factory') returning id",(tenant,)).fetchone()[0]
        admin.execute("insert into party_role(tenant_id,party_id,role_type) values(%s,%s,'supplier')",(tenant,party))
        admin.execute("insert into supplier_profile(tenant_id,party_id) values(%s,%s)",(tenant,party))
        product=admin.execute("insert into supplier_product(tenant_id,supplier_party_id,sku,product_name) values(%s,%s,'SKU-1','Widget') returning id",(tenant,party)).fetchone()[0]
        admin.execute("insert into supplier_quote(tenant_id,supplier_party_id,supplier_product_id,quote_ref,version,quoted_on,currency,unit_price) values(%s,%s,%s,'Q1',1,current_date,'GBP',2.5)",(tenant,party,product))
        admin.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            admin.execute("insert into supplier_quote(tenant_id,supplier_party_id,supplier_product_id,quote_ref,version,quoted_on,currency,unit_price) values(%s,%s,%s,'Q1',2,current_date,'GBP',2.4)",(tenant,party,product))
        admin.rollback()
        admin.execute("insert into supplier_document(tenant_id,supplier_party_id,document_type,title,storage_key) values(%s,%s,'quote','Private quote','tenant/key')",(tenant,party))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)",(tenant,))
                assert app.execute("select count(*) from supplier_document").fetchone()[0] == 0
                app.execute("select set_config('app.access_scopes','supplier:documents',true)")
                assert app.execute("select count(*) from supplier_document").fetchone()[0] == 1
        finally:
            admin.execute("delete from tenant where id=%s", (tenant,))
            admin.commit()
