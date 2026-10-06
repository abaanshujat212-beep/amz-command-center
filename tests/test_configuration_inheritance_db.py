import os
import uuid
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

from services.config.inheritance import (
    detach_override,
    publish_override,
    resolve_effective_configuration,
    rollback_override,
)

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_version_precedence_detach_rollback_rbac_hard_guards_and_rls():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    owner, viewer = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for user, name in ((owner, "owner"), (viewer, "viewer")):
            admin.execute(
                "insert into auth.auth_user(id,name,email) values(%s,%s,%s)",
                (user, name, f"{user}@test"),
            )
        for tenant in (tenant_a, tenant_b):
            admin.execute("select set_tenant(%s)", (tenant,))
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'config',%s)", (tenant, str(tenant))
            )
        admin.execute("select set_tenant(%s)", (tenant_a,))
        admin.execute(
            "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner'),(%s,%s,'viewer')",
            (tenant_a, owner, tenant_a, viewer),
        )
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                tenant_version = publish_override(
                    app,
                    tenant_id=str(tenant_a),
                    scope_type="tenant",
                    scope_id=str(tenant_a),
                    values={"max_bid": 8, "dry_run": False},
                    actor_user_id=str(owner),
                    reason="tenant policy",
                )
                publish_override(
                    app,
                    tenant_id=str(tenant_a),
                    scope_type="marketplace",
                    scope_id="uk",
                    values={"max_bid": 12},
                    actor_user_id=str(owner),
                    reason="market policy",
                )
                entity_version = publish_override(
                    app,
                    tenant_id=str(tenant_a),
                    scope_type="entity",
                    scope_id="campaign:c1",
                    values={"max_bid": 75},
                    actor_user_id=str(owner),
                    reason="entity experiment",
                )
                current = resolve_effective_configuration(
                    app,
                    tenant_id=str(tenant_a),
                    scopes={
                        "tenant": str(tenant_a),
                        "marketplace": "uk",
                        "entity": "campaign:c1",
                    },
                )
                assert current.values["max_bid"] == Decimal("50")
                assert current.sources["max_bid"].hard_guard is True
                assert current.values["dry_run"] is False

                detach_override(
                    app,
                    tenant_id=str(tenant_a),
                    scope_type="entity",
                    scope_id="campaign:c1",
                    actor_user_id=str(owner),
                    reason="end experiment",
                )
                detached = resolve_effective_configuration(
                    app,
                    tenant_id=str(tenant_a),
                    scopes={
                        "tenant": str(tenant_a),
                        "marketplace": "uk",
                        "entity": "campaign:c1",
                    },
                )
                assert detached.values["max_bid"] == Decimal("12")
                assert detached.sources["max_bid"].level == "marketplace"

                rollback_override(
                    app,
                    rollback_to_id=entity_version,
                    tenant_id=str(tenant_a),
                    scope_type="entity",
                    scope_id="campaign:c1",
                    actor_user_id=str(owner),
                    reason="restore experiment",
                )
                assert app.execute(
                    """select array_agg(operation order by version)
                             from configuration_override_version
                            where scope_type='entity' and scope_id='campaign:c1'"""
                ).fetchone()["array_agg"] == ["apply", "detach", "rollback"]
                app.commit()
                # Tenant context is transaction-local; restore it after commit.
                app.execute("select set_tenant(%s)", (tenant_a,))
                with pytest.raises(PermissionError):
                    publish_override(
                        app,
                        tenant_id=str(tenant_a),
                        scope_type="tenant",
                        scope_id=str(tenant_a),
                        values={"dry_run": True},
                        actor_user_id=str(viewer),
                        reason="not authorized",
                    )
                with pytest.raises(psycopg.errors.RaiseException, match="hard guard"):
                    publish_override(
                        app,
                        tenant_id=str(tenant_a),
                        scope_type="tenant",
                        scope_id=str(tenant_a),
                        values={"allow_direct_amazon_mutation": True},
                        actor_user_id=str(owner),
                        reason="unsafe",
                    )
                app.rollback()
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert (
                    app.execute("select count(*) n from configuration_override_version").fetchone()[
                        "n"
                    ]
                    == 0
                )
                assert tenant_version
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=any(%s)", ([owner, viewer],))
