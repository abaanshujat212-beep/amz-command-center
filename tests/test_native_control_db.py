import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.actions import state_machine as sm
from services.actions.native_controls import load_native_control_state

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


@pytest.mark.parametrize("destination", [{"campaign_id": "destination"}, {}, {"campaign_id": ""}])
def test_harvest_checks_destination_and_never_falls_back_to_source(destination):
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN, row_factory=dict_row) as db:
        try:
            db.execute("select set_tenant(%s)", (tenant_id,))
            db.execute("insert into tenant(id,name,slug) values(%s,'Harvest controls',%s)", (tenant_id, str(tenant_id)))
            for campaign, strategy in [("source", "fixed"), ("destination", "dynamic_up_down")]:
                db.execute("""insert into campaign_native_control_state(
                    tenant_id,campaign_id,bidding_strategy,bidding_strategy_supported,
                    source_observed_at,source_api_version,source_fingerprint,source_record)
                    values(%s,%s,%s,true,now(),'sp-campaigns-v3',%s,'{}')""",
                    (tenant_id, campaign, strategy, "b" * 64))
            db.execute("""insert into action(id,tenant_id,entity_type,entity_id,action_type,
                before_value,after_value,status,idempotency_key)
                values(%s,%s,'search_term','term','create_keyword',%s,%s,'pending',%s)""",
                (action_id, tenant_id, Jsonb({"campaign_id": "source"}),
                 Jsonb({"campaign_id": "source", "destination": destination}), str(action_id)))
            action = sm.Action(id=str(action_id), tenant_id=str(tenant_id), entity_type="search_term",
                               entity_id="term", action_type="create_keyword", before_value={},
                               after_value={}, status=sm.Status.PENDING)
            with db.cursor() as cur:
                state = load_native_control_state(cur, action)
            if destination.get("campaign_id"):
                assert state.campaign_id == "destination"
                assert state.bidding_strategy == "dynamic_up_down"
            else:
                assert state is None
        finally:
            db.rollback()
