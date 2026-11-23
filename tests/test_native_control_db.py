import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_native_control_snapshots_are_idempotent_append_only_and_tenant_scoped():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    fingerprint = "a" * 64
    with psycopg.connect(ADMIN) as db:
        db.execute("insert into tenant(id,name,slug) values(%s,'Native A',%s),(%s,'Native B',%s)", (tenant_a, str(tenant_a), tenant_b, str(tenant_b)))
        sql = """insert into campaign_native_control_state(
            tenant_id,campaign_id,bidding_strategy,bidding_strategy_supported,
            source_observed_at,source_api_version,source_fingerprint,source_record)
            values(%s,'campaign-1','fixed',true,'2026-11-23T10:00:00Z','sp-campaigns-v3',%s,'{}')
            on conflict(tenant_id,campaign_id,source_api_version,source_fingerprint,source_observed_at) do nothing"""
        db.execute(sql, (tenant_a, fingerprint))
        db.execute(sql, (tenant_a, fingerprint))
        db.execute(sql, (tenant_b, fingerprint))
        db.commit()
        try:
            with psycopg.connect(APP) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute("select count(*) from campaign_native_control_state").fetchone()[0] == 1
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute("select count(*) from campaign_native_control_state").fetchone()[0] == 1
                assert app.execute("select has_table_privilege(current_user,'campaign_native_control_state','UPDATE')").fetchone()[0] is False
                assert app.execute("select has_table_privilege(current_user,'campaign_native_control_state','DELETE')").fetchone()[0] is False
        finally:
            db.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            db.commit()
