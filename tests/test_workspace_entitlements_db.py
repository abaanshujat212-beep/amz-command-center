import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP",
    "postgresql://axaty_app:axaty_app@localhost:5432/axaty",
)


def _user(admin, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    admin.execute(
        "insert into auth.auth_user(id,name,email) values(%s,%s,%s)",
        (user_id, name, f"{user_id}@example.test"),
    )
    return user_id


def _tenant(admin, name: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    admin.execute(
        "insert into tenant(id,name,slug) values(%s,%s,%s)",
        (tenant_id, name, f"{name}-{tenant_id}"),
    )
    return tenant_id


def test_workspace_defaults_limits_and_session_discovery():
    workspace_id = uuid.uuid4()
    token = f"workspace-{uuid.uuid4()}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        owner = _user(admin, "owner")
        second = _user(admin, "second")
        tenant_a = _tenant(admin, "client-a")
        tenant_b = _tenant(admin, "client-b")
        admin.execute(
            "insert into workspace(id,name,slug) values(%s,'Agency','agency-' || %s)",
            (workspace_id, workspace_id),
        )
        try:
            defaults = admin.execute(
                "select portfolio_enabled,cross_account_summary_enabled,"
                " portfolio_alerts_enabled,max_connected_accounts,max_team_seats"
                " from workspace_entitlement where workspace_id=%s",
                (workspace_id,),
            ).fetchone()
            assert defaults == (False, False, False, 1, 1)

            admin.execute(
                "insert into workspace_member(workspace_id,user_id,role,"
                " can_view_portfolio,can_operate_tenants)"
                " values(%s,%s,'owner',true,false)",
                (workspace_id, owner),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="seat limit"):
                admin.execute(
                    "insert into workspace_member(workspace_id,user_id,role)"
                    " values(%s,%s,'viewer')",
                    (workspace_id, second),
                )

            admin.execute(
                "insert into workspace_tenant(workspace_id,tenant_id) values(%s,%s)",
                (workspace_id, tenant_a),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="account limit"):
                admin.execute(
                    "insert into workspace_tenant(workspace_id,tenant_id) values(%s,%s)",
                    (workspace_id, tenant_b),
                )

            admin.execute(
                "insert into auth.auth_session(id,expires_at,token,updated_at,user_id)"
                " values(%s,%s,%s,now(),%s)",
                (
                    uuid.uuid4(),
                    dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
                    token,
                    owner,
                ),
            )
            with psycopg.connect(APP_URL, autocommit=True) as app:
                row = app.execute("select * from session_workspaces(%s)", (token,)).fetchone()
                assert row[0] == str(workspace_id)
                assert row[4] is True
                assert row[5] is False
                assert row[6:9] == (False, False, False)
                assert app.execute(
                    "select count(*) from session_workspaces(%s)",
                    ("invalid-token",),
                ).fetchone()[0] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("select * from workspace_member")
        finally:
            admin.execute("delete from workspace where id=%s", (workspace_id,))
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=any(%s)", ([owner, second],))


def test_workspace_limits_can_be_increased_without_commercial_plan_names():
    workspace_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        first = _user(admin, "first")
        second = _user(admin, "second")
        tenant_a = _tenant(admin, "limit-a")
        tenant_b = _tenant(admin, "limit-b")
        admin.execute(
            "insert into workspace(id,name,slug) values(%s,'Agency 2','agency-' || %s)",
            (workspace_id, workspace_id),
        )
        try:
            admin.execute(
                "update workspace_entitlement set max_team_seats=2,"
                " max_connected_accounts=2,portfolio_enabled=true where workspace_id=%s",
                (workspace_id,),
            )
            for user_id, role in ((first, "owner"), (second, "analyst")):
                admin.execute(
                    "insert into workspace_member(workspace_id,user_id,role) values(%s,%s,%s)",
                    (workspace_id, user_id, role),
                )
            for tenant_id in (tenant_a, tenant_b):
                admin.execute(
                    "insert into workspace_tenant(workspace_id,tenant_id) values(%s,%s)",
                    (workspace_id, tenant_id),
                )
            assert admin.execute(
                "select count(*) from workspace_member where workspace_id=%s",
                (workspace_id,),
            ).fetchone()[0] == 2
            assert admin.execute(
                "select count(*) from workspace_tenant where workspace_id=%s",
                (workspace_id,),
            ).fetchone()[0] == 2
        finally:
            admin.execute("delete from workspace where id=%s", (workspace_id,))
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=any(%s)", ([first, second],))
