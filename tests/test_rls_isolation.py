"""Cross-tenant isolation gate.

Phase 0 does not close until this passes. Tenant #1 is a real client's Amazon
account, so a leak here is a breach, not a bug.

Run with:  make test
"""

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db

ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")

TENANT_TABLES = [
    "tenant_member",
    "tenant_settings",
    "amazon_connection",
    "ads_profile",
    "selling_account",
    "sync_watermark",
    "pipeline_run",
    "audit_log",
]


@pytest.fixture(scope="module")
def tenants():
    """Create two tenants with one row each in every tenant-scoped table."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        for tid, name in ((a, "tenant-a"), (b, "tenant-b")):
            conn.execute("insert into tenant (id, name, slug) values (%s, %s, %s)", (tid, name, name))
            conn.execute("insert into tenant_settings (tenant_id) values (%s)", (tid,))
            conn.execute(
                "insert into tenant_member (tenant_id, user_id, role) values (%s, %s, 'owner')",
                (tid, uuid.uuid4()),
            )
            conn.execute(
                "insert into amazon_connection (tenant_id, provider) values (%s, 'ads_api')",
                (tid,),
            )
            conn.execute(
                "insert into sync_watermark (tenant_id, dataset, last_status)"
                " values (%s, 'ads_sp_campaign_daily', 'success')",
                (tid,),
            )
            conn.execute(
                "insert into pipeline_run (tenant_id, dataset, status) values (%s, 'x', 'success')",
                (tid,),
            )
            conn.execute(
                "insert into audit_log (tenant_id, action) values (%s, 'seed')", (tid,)
            )
    yield a, b
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("delete from tenant where id = any(%s)", ([a, b],))


def _app_conn():
    return psycopg.connect(APP_URL)


def test_sees_only_own_rows(tenants):
    a, b = tenants
    with _app_conn() as conn, conn.transaction():
        conn.execute("select set_tenant(%s)", (a,))
        for table in TENANT_TABLES:
            rows = conn.execute(
                f"select count(*) from {table} where tenant_id = %s", (b,)
            ).fetchone()[0]
            assert rows == 0, f"{table} leaked tenant B rows to tenant A"


def test_fails_closed_without_tenant_context(tenants):
    """No app.tenant_id set must mean zero rows, never all rows."""
    with _app_conn() as conn, conn.transaction():
        for table in TENANT_TABLES:
            rows = conn.execute(f"select count(*) from {table}").fetchone()[0]
            assert rows == 0, f"{table} returned rows with no tenant context"


def test_cannot_update_other_tenant(tenants):
    a, b = tenants
    with _app_conn() as conn, conn.transaction():
        conn.execute("select set_tenant(%s)", (a,))
        cur = conn.execute(
            "update tenant_settings set automation_enabled = true where tenant_id = %s", (b,)
        )
        assert cur.rowcount == 0


def test_cannot_delete_other_tenant(tenants):
    a, b = tenants
    with _app_conn() as conn, conn.transaction():
        conn.execute("select set_tenant(%s)", (a,))
        cur = conn.execute("delete from audit_log where tenant_id = %s", (b,))
        assert cur.rowcount == 0


def test_cannot_insert_for_other_tenant(tenants):
    """WITH CHECK must reject writes stamped with someone else's tenant_id."""
    a, b = tenants
    with _app_conn() as conn:
        with pytest.raises(psycopg.errors.Error):
            with conn.transaction():
                conn.execute("select set_tenant(%s)", (a,))
                conn.execute(
                    "insert into audit_log (tenant_id, action) values (%s, 'evil')", (b,)
                )
