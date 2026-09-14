import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def seed_party(conn, tenant_id, name):
    return conn.execute(
        "insert into party(tenant_id,party_kind,display_name,normalized_name) values(%s,'organization',%s,%s) returning id",
        (tenant_id, name, name.lower()),
    ).fetchone()[0]


def test_multi_role_duplicate_and_tenant_isolation():
    a, b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("insert into tenant(id,name,slug) values(%s,'A',%s),(%s,'B',%s)", (a, str(a), b, str(b)))
        pa, pb = seed_party(admin, a, "Acme"), seed_party(admin, b, "Beta")
        admin.execute("insert into party_role values(%s,%s,'supplier','{}',now()),(%s,%s,'agent','{}',now())", (a, pa, a, pa))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (a,))
                assert app.execute("select count(*) from party where id=%s", (pb,)).fetchone()[0] == 0
                assert app.execute("select count(*) from party_role where party_id=%s", (pa,)).fetchone()[0] == 2
                with pytest.raises(psycopg.errors.UniqueViolation):
                    app.execute("insert into party(tenant_id,party_kind,display_name,normalized_name) values(%s,'organization','ACME','acme')", (a,))
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([a, b],))
            admin.commit()


def test_restricted_channels_require_sensitive_scope():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("insert into tenant(id,name,slug) values(%s,'Sensitive',%s)", (tenant_id, str(tenant_id)))
        party_id = seed_party(admin, tenant_id, "Sensitive Party")
        contact_id = admin.execute("insert into contact(tenant_id,party_id,full_name) values(%s,%s,'Person') returning id", (tenant_id, party_id)).fetchone()[0]
        admin.execute("insert into contact_channel(tenant_id,contact_id,channel_type,value,normalized_value,sensitivity) values(%s,%s,'email','secret@example.com','secret@example.com','restricted')", (tenant_id, contact_id))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                assert app.execute("select count(*) from contact_channel").fetchone()[0] == 0
                app.execute("select set_config('app.access_scopes','contacts:sensitive',true)")
                assert app.execute("select value from contact_channel").fetchone()[0] == "secret@example.com"
        finally:
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.commit()
