import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")
DEFINITION = {"schemaVersion": 1, "widgets": [{"id": "health", "type": "table", "query": "pipeline.health", "layout": {"x": 0, "y": 0, "w": 12, "h": 4}}], "globalFilters": []}


def _context(conn, tenant, user, role):
    conn.execute("select set_tenant(%s)", (tenant,))
    conn.execute("select set_dashboard_actor(%s,%s)", (user, role))


def test_private_team_visibility_versions_and_tenant_isolation():
    tenant_a, tenant_b, owner, peer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for user in (owner, peer):
            admin.execute("insert into auth.auth_user(id,name,email) values(%s,'user',%s)", (user, f"{user}@test"))
        for tenant in (tenant_a, tenant_b):
            admin.execute("insert into tenant(id,name,slug) values(%s,'dash',%s)", (tenant, str(tenant)))
        admin.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner'),(%s,%s,'user')", (tenant_a, owner, tenant_a, peer))
        admin.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')", (tenant_b, owner))
        try:
            with psycopg.connect(APP_URL) as app:
                _context(app, tenant_a, owner, "owner")
                private_id = app.execute("insert into dashboard(tenant_id,name,visibility,owner_user_id) values(%s,'Private','private',%s) returning id", (tenant_a, owner)).fetchone()[0]
                team_id = app.execute("insert into dashboard(tenant_id,name,visibility,owner_user_id) values(%s,'Team','team',%s) returning id", (tenant_a, owner)).fetchone()[0]
                for dashboard_id in (private_id, team_id):
                    app.execute("insert into dashboard_version(tenant_id,dashboard_id,version,definition,change_summary,created_by) values(%s,%s,1,%s,'initial',%s)", (tenant_a, dashboard_id, Jsonb(DEFINITION), owner))
                app.commit()

                _context(app, tenant_a, peer, "user")
                assert app.execute("select name from dashboard order by name").fetchall() == [("Team",)]
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("insert into dashboard_version(tenant_id,dashboard_id,version,definition,change_summary,created_by) values(%s,%s,2,%s,'unauthorized',%s)", (tenant_a, team_id, Jsonb(DEFINITION), peer))
                app.rollback()

                _context(app, tenant_b, owner, "owner")
                assert app.execute("select count(*) from dashboard").fetchone()[0] == 0
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=any(%s)", ([owner, peer],))


def test_database_rejects_non_allowlisted_dashboard_definition():
    tenant, owner = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("insert into auth.auth_user(id,name,email) values(%s,'owner',%s)", (owner, f"{owner}@test"))
        admin.execute("insert into tenant(id,name,slug) values(%s,'dash',%s)", (tenant, str(tenant)))
        admin.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')", (tenant, owner))
        try:
            with psycopg.connect(APP_URL) as app:
                _context(app, tenant, owner, "owner")
                dashboard_id = app.execute("insert into dashboard(tenant_id,name,visibility,owner_user_id) values(%s,'Bad','private',%s) returning id", (tenant, owner)).fetchone()[0]
                bad = {**DEFINITION, "widgets": [{**DEFINITION["widgets"][0], "query": "raw.sql"}]}
                with pytest.raises(psycopg.errors.CheckViolation):
                    app.execute("insert into dashboard_version(tenant_id,dashboard_id,version,definition,change_summary,created_by) values(%s,%s,1,%s,'bad',%s)", (tenant, dashboard_id, Jsonb(bad), owner))
        finally:
            admin.execute("delete from tenant where id=%s", (tenant,))
            admin.execute("delete from auth.auth_user where id=%s", (owner,))
