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


def _tenant(admin, prefix):
    tenant_id = uuid.uuid4()
    admin.execute(
        "insert into tenant(id,name,slug) values(%s,%s,%s)",
        (tenant_id, prefix, f"{prefix}-{tenant_id}"),
    )
    return tenant_id


def _provider_rows(admin, tenant_id):
    connection_id = admin.execute(
        "insert into amazon_connection(tenant_id,provider) values(%s,'ads_api') returning id",
        (tenant_id,),
    ).fetchone()[0]
    selling_connection = admin.execute(
        "insert into amazon_connection(tenant_id,provider) values(%s,'sp_api') returning id",
        (tenant_id,),
    ).fetchone()[0]
    selling_id = admin.execute(
        "insert into selling_account(tenant_id,connection_id,selling_partner_id)"
        " values(%s,%s,%s) returning id",
        (tenant_id, selling_connection, f"seller-{tenant_id}"),
    ).fetchone()[0]
    profile_id = admin.execute(
        "insert into ads_profile(tenant_id,connection_id,profile_id,country_code,currency)"
        " values(%s,%s,%s,'GB','GBP') returning id",
        (tenant_id, connection_id, abs(hash(tenant_id)) % 2_000_000_000),
    ).fetchone()[0]
    return selling_id, profile_id


def test_explicit_amazon_hierarchy_reuses_provider_identities():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_id = _tenant(admin, "hierarchy")
        selling_id, profile_id = _provider_rows(admin, tenant_id)
        try:
            brand_id = admin.execute(
                "insert into brand(tenant_id,name,slug) values(%s,'Hooks','hooks') returning id",
                (tenant_id,),
            ).fetchone()[0]
            account_id = admin.execute(
                "insert into channel_account(tenant_id,brand_id,label,selling_account_id)"
                " values(%s,%s,'Amazon UK',%s) returning id",
                (tenant_id, brand_id, selling_id),
            ).fetchone()[0]
            market_id = admin.execute(
                "insert into marketplace_context(tenant_id,channel_account_id,"
                " marketplace_id,country_code,currency)"
                " values(%s,%s,'A1F83G8C2ARO7P','GB','GBP') returning id",
                (tenant_id, account_id),
            ).fetchone()[0]
            admin.execute(
                "insert into advertising_profile_context"
                "(tenant_id,marketplace_context_id,ads_profile_id) values(%s,%s,%s)",
                (tenant_id, market_id, profile_id),
            )
            assert admin.execute(
                "select count(*) from advertising_profile_context where tenant_id=%s",
                (tenant_id,),
            ).fetchone()[0] == 1
        finally:
            admin.execute("delete from tenant where id=%s", (tenant_id,))


def test_unknown_channel_and_cross_tenant_links_fail_closed():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_a = _tenant(admin, "hier-a")
        tenant_b = _tenant(admin, "hier-b")
        selling_b, _ = _provider_rows(admin, tenant_b)
        try:
            brand_a = admin.execute(
                "insert into brand(tenant_id,name,slug) values(%s,'A','a') returning id",
                (tenant_a,),
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    "insert into channel_account(tenant_id,brand_id,channel,label)"
                    " values(%s,%s,'daraz','unsupported')",
                    (tenant_a, brand_a),
                )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                admin.execute(
                    "insert into channel_account"
                    "(tenant_id,brand_id,label,selling_account_id) values(%s,%s,'cross',%s)",
                    (tenant_a, brand_a, selling_b),
                )
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))


def test_context_tables_are_forced_rls_isolated_and_unmapped_rows_survive():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_a = _tenant(admin, "rls-a")
        tenant_b = _tenant(admin, "rls-b")
        selling_b, profile_b = _provider_rows(admin, tenant_b)
        brand_b = admin.execute(
            "insert into brand(tenant_id,name,slug) values(%s,'B','b') returning id",
            (tenant_b,),
        ).fetchone()[0]
    try:
        with psycopg.connect(APP_URL) as app, app.transaction():
            app.execute("select set_tenant(%s)", (tenant_a,))
            for table in (
                "brand",
                "channel_account",
                "marketplace_context",
                "advertising_profile_context",
            ):
                assert app.execute(f"select count(*) from {table}").fetchone()[0] == 0
            with pytest.raises(psycopg.errors.Error):
                app.execute(
                    "insert into brand(tenant_id,name,slug) values(%s,'leak','leak')",
                    (tenant_b,),
                )
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            assert admin.execute(
                "select count(*) from selling_account where id=%s", (selling_b,)
            ).fetchone()[0] == 1
            assert admin.execute(
                "select count(*) from ads_profile where id=%s", (profile_b,)
            ).fetchone()[0] == 1
            assert admin.execute(
                "select count(*) from channel_account where brand_id=%s", (brand_b,)
            ).fetchone()[0] == 0
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
