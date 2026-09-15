import datetime as dt
import os
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")
ROOT = Path(__file__).parents[1]


def test_read_only_portfolio_discovery_and_alert_entitlement():
    workspace_id, user_id, tenant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = f"portfolio-read-{uuid.uuid4()}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("insert into auth.auth_user(id,name,email) values(%s,'reader',%s)", (user_id, f"{user_id}@test"))
        admin.execute("insert into tenant(id,name,slug) values(%s,'Client',%s)", (tenant_id, f"client-{tenant_id}"))
        admin.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'viewer')", (tenant_id, user_id))
        admin.execute("insert into workspace(id,name,slug) values(%s,'Agency',%s)", (workspace_id, f"agency-{workspace_id}"))
        try:
            admin.execute("update workspace_entitlement set portfolio_enabled=true,cross_account_summary_enabled=true,portfolio_alerts_enabled=false,max_connected_accounts=2 where workspace_id=%s", (workspace_id,))
            admin.execute("insert into workspace_member(workspace_id,user_id,role,can_view_portfolio,can_operate_tenants) values(%s,%s,'viewer',true,false)", (workspace_id, user_id))
            admin.execute("insert into workspace_tenant(workspace_id,tenant_id) values(%s,%s)", (workspace_id, tenant_id))
            admin.execute("insert into auth.auth_session(id,expires_at,token,updated_at,user_id) values(%s,%s,%s,now(),%s)", (uuid.uuid4(), dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1), token, user_id))
            with psycopg.connect(APP_URL, autocommit=True) as app:
                rows = app.execute("select * from session_workspace_portfolio_tenants(%s,%s,false)", (token, workspace_id)).fetchall()
                assert rows == [(str(tenant_id), "Client", f"client-{tenant_id}", "viewer")]
                assert app.execute("select count(*) from session_workspace_portfolio_tenants(%s,%s,true)", (token, workspace_id)).fetchone()[0] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("select * from workspace_tenant")
            admin.execute("update workspace_entitlement set portfolio_alerts_enabled=true where workspace_id=%s", (workspace_id,))
            with psycopg.connect(APP_URL, autocommit=True) as app:
                assert app.execute("select count(*) from session_workspace_portfolio_tenants(%s,%s,true)", (token, workspace_id)).fetchone()[0] == 1
            admin.execute("delete from tenant_member where tenant_id=%s and user_id=%s", (tenant_id, user_id))
            with psycopg.connect(APP_URL, autocommit=True) as app:
                assert app.execute("select count(*) from session_workspace_portfolio_tenants(%s,%s,false)", (token, workspace_id)).fetchone()[0] == 0
        finally:
            admin.execute("delete from workspace where id=%s", (workspace_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))


def test_portfolio_discovery_migration_is_reversible():
    up = (ROOT / "packages/db/migrations/0031_portfolio_read_discovery.sql").read_text()
    down = (ROOT / "packages/db/migrations/down/0031_portfolio_read_discovery.sql").read_text()
    assert "can_view_portfolio = true" in up
    assert "cross_account_summary_enabled = true" in up
    assert "p_require_alerts" in up and "portfolio_alerts_enabled = true" in up
    assert "tenant_member" in up
    assert "drop function if exists public.session_workspace_portfolio_tenants" in down
