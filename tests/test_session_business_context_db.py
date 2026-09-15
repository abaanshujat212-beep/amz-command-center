import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_session_context_is_nullable_and_operate_authorization_fails_closed():
    user_id, workspace_id, tenant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = f"context-{uuid.uuid4()}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("insert into auth.auth_user(id,name,email) values(%s,'operator',%s)", (user_id, f"{user_id}@example.test"))
        admin.execute("insert into tenant(id,name,slug) values(%s,'client',%s)", (tenant_id, f"client-{tenant_id}"))
        admin.execute("insert into workspace(id,name,slug) values(%s,'agency',%s)", (workspace_id, f"agency-{workspace_id}"))
        try:
            admin.execute("update workspace_entitlement set portfolio_enabled=true where workspace_id=%s", (workspace_id,))
            admin.execute("insert into workspace_member(workspace_id,user_id,role,can_view_portfolio,can_operate_tenants) values(%s,%s,'owner',true,false)", (workspace_id, user_id))
            admin.execute("insert into workspace_tenant(workspace_id,tenant_id) values(%s,%s)", (workspace_id, tenant_id))
            session_id = uuid.uuid4()
            admin.execute("insert into auth.auth_session(id,expires_at,token,updated_at,user_id) values(%s,%s,%s,now(),%s)", (session_id, dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1), token, user_id))
            row = admin.execute("select active_workspace_id,active_brand_id,active_channel_account_id,active_marketplace_context_id,active_ads_profile_id from auth.auth_session where id=%s", (session_id,)).fetchone()
            assert row == (None, None, None, None, None)
            with psycopg.connect(APP_URL, autocommit=True) as app:
                assert app.execute("select * from session_workspace_tenant_authorization(%s,%s,%s)", (token, workspace_id, tenant_id)).fetchone() is None
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("select * from workspace_tenant")
            admin.execute("update workspace_member set can_operate_tenants=true where workspace_id=%s and user_id=%s", (workspace_id, user_id))
            with psycopg.connect(APP_URL, autocommit=True) as app:
                allowed = app.execute("select * from session_workspace_tenant_authorization(%s,%s,%s)", (token, workspace_id, tenant_id)).fetchone()
                assert allowed == ('owner', True, True)
                assert app.execute("select * from session_workspace_tenant_authorization(%s,%s,%s)", ('expired-or-forged', workspace_id, tenant_id)).fetchone() is None
            admin.execute("delete from workspace_tenant where workspace_id=%s and tenant_id=%s", (workspace_id, tenant_id))
            with psycopg.connect(APP_URL, autocommit=True) as app:
                assert app.execute("select * from session_workspace_tenant_authorization(%s,%s,%s)", (token, workspace_id, tenant_id)).fetchone() is None
        finally:
            admin.execute("delete from auth.auth_session where user_id=%s", (user_id,))
            admin.execute("delete from workspace where id=%s", (workspace_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))


def test_context_migration_is_sequential_and_reversible():
    root = os.path.dirname(os.path.dirname(__file__))
    up = open(os.path.join(root, "packages/db/migrations/0030_session_business_context.sql")).read()
    down = open(os.path.join(root, "packages/db/migrations/down/0030_session_business_context.sql")).read()
    for field in ("active_workspace_id", "active_brand_id", "active_channel_account_id", "active_marketplace_context_id", "active_ads_profile_id"):
        assert field in up
        assert field in down
    assert "security definer" in up.lower()
    assert "can_operate_tenants = true" in up
    assert "portfolio_enabled = true" in up
