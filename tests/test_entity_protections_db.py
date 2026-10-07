import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.rules.protections import active_protection

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_protection_precedence_expiry_release_audit_and_rls():
    tenant_a, tenant_b, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'owner',%s)",
            (owner, f"{owner}@test"),
        )
        for tenant in (tenant_a, tenant_b):
            admin.execute("select set_tenant(%s)", (tenant,))
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'protections',%s)",
                (tenant, str(tenant)),
            )
        admin.execute("select set_tenant(%s)", (tenant_a,))
        admin.execute(
            "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')",
            (tenant_a, owner),
        )
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                protection = app.execute(
                    """insert into entity_protection(tenant_id,entity_type,entity_value,product_scope,policy,duration,reason,created_by) values(%s,'search_term','womens shoes','mens-shoes','protect','persistent','manual exclusion',%s) returning id""",
                    (tenant_a, owner),
                ).fetchone()["id"]
                decision = active_protection(
                    app,
                    tenant_id=str(tenant_a),
                    entity_type="search_term",
                    entity_value="WOMENS SHOES",
                    product_scope="mens-shoes",
                    action_type="add_negative_exact",
                )
                assert decision.blocked and decision.protection_id == str(protection)
                assert (
                    app.execute("select count(*) n from entity_protection_event").fetchone()["n"]
                    == 1
                )
                app.execute(
                    "insert into entity_protection_event(tenant_id,protection_id,event_type,reason,actor_user_id) values(%s,%s,'released','return control',%s)",
                    (tenant_a, protection, owner),
                )
                assert not active_protection(
                    app,
                    tenant_id=str(tenant_a),
                    entity_type="search_term",
                    entity_value="womens shoes",
                    product_scope="mens-shoes",
                    action_type="add_negative_exact",
                ).blocked
                with pytest.raises(psycopg.errors.CheckViolation):
                    app.execute(
                        """insert into entity_protection(tenant_id,entity_type,entity_value,policy,duration,expires_at,reason,created_by) values(%s,'asin','B000TEST','protect','temporary',%s,'expired',%s)""",
                        (tenant_a, dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1), owner),
                    )
                app.rollback()
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute("select count(*) n from entity_protection").fetchone()["n"] == 0
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (owner,))
