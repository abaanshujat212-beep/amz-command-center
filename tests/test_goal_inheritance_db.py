import datetime as dt
import os
import uuid
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

from services.config.goal_resolver import resolve_effective_goal

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def insert_goal(conn, tenant, scope, scope_id, start, end=None, **values):
    columns = list(values)
    placeholders = ",".join(["%s"] * (6 + len(columns)))
    return conn.execute(
        f"""insert into ppc_goal_override(
                tenant_id,scope_type,scope_id,effective_from,effective_to,reason,{",".join(columns)})
              values({placeholders}) returning id""",
        (tenant, scope, scope_id, start, end, "test", *values.values()),
    ).fetchone()[0]


def test_goal_precedence_dates_conflicts_immutability_and_rls():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    day = dt.date(2026, 10, 6)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for tenant in (tenant_a, tenant_b):
            admin.execute("select set_tenant(%s)", (tenant,))
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'goals',%s)", (tenant, str(tenant))
            )
        try:
            admin.execute("select set_tenant(%s)", (tenant_a,))
            account_id = insert_goal(
                admin,
                tenant_a,
                "account",
                "account-1",
                day - dt.timedelta(days=30),
                target_acos=0.30,
                min_acos=0.10,
                profit_floor=0.05,
            )
            campaign_id = insert_goal(
                admin,
                tenant_a,
                "campaign",
                "campaign-1",
                day,
                target_acos=0.20,
                max_acos=0.25,
            )
            insert_goal(
                admin,
                tenant_a,
                "keyword",
                "keyword-1",
                day + dt.timedelta(days=1),
                target_acos=0.05,
            )
            insert_goal(
                admin,
                tenant_a,
                "portfolio",
                "expired-portfolio",
                day - dt.timedelta(days=30),
                day - dt.timedelta(days=1),
                target_acos=0.01,
            )
            with pytest.raises(psycopg.errors.ExclusionViolation):
                insert_goal(admin, tenant_a, "campaign", "campaign-1", day, target_acos=0.21)
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    """insert into ppc_goal_override(
                         tenant_id,scope_type,scope_id,effective_from,reason)
                       values(%s,'account','empty',%s,'test')""",
                    (tenant_a, day),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                insert_goal(
                    admin,
                    tenant_a,
                    "account",
                    "invalid-range",
                    day,
                    min_acos=0.5,
                    max_acos=0.2,
                )
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                admin.execute(
                    "update ppc_goal_override set target_acos=0.22 where id=%s", (campaign_id,)
                )

            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                result = resolve_effective_goal(
                    app,
                    tenant_id=str(tenant_a),
                    scopes={
                        "account": "account-1",
                        "campaign": "campaign-1",
                        "keyword": "keyword-1",
                    },
                    as_of=day,
                )
                assert result.values["target_acos"] == Decimal("0.20")
                assert result.sources["target_acos"].scope_type == "campaign"
                assert result.values["min_acos"] == Decimal("0.10")
                assert app.execute("select count(*) n from ppc_goal_override").fetchone()["n"] == 4
                assert (
                    app.execute("select count(*) n from ppc_goal_override_event").fetchone()["n"]
                    == 4
                )

                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute("select count(*) n from ppc_goal_override").fetchone()["n"] == 0
            assert account_id is not None
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
