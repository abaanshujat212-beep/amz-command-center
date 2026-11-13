"""Experiment registrations and action-learning evidence stay tenant isolated."""

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


@pytest.fixture
def experiment_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Experiment A',%s)", (tenant_a, str(tenant_a)))
        db.execute("insert into tenant(id,name,slug) values(%s,'Experiment B',%s)", (tenant_b, str(tenant_b)))
        experiment = db.execute(
            """insert into action_experiment(tenant_id,name,hypothesis,success_metric,control_description,
                   entity_type,entity_id,start_date) values(%s,'Bid test','Lower bids reduce ACOS','acos',
                   'Unchanged keywords','keyword','kw-1','2026-01-01') returning id""", (tenant_a,),
        ).fetchone()["id"]
        yield db, tenant_a, tenant_b, experiment
        db.rollback()


def test_experiment_and_outcomes_are_rls_isolated_and_outcomes_append_only(experiment_db):
    db, tenant_a, tenant_b, experiment = experiment_db
    db.execute("""insert into action_experiment_outcome(tenant_id,experiment_id,outcome_kind,outcome,
        metric_name,metric_value,sample_size,observed_at,evidence_note) values(%s,%s,'operator_observation',
        'improved','acos',0.22,40,now(),'manual review')""", (tenant_a, experiment))
    with db.transaction():
        db.execute("set local role axaty_app")
        db.execute("select set_config('app.tenant_id',%s,true)", (str(tenant_a),))
        assert db.execute("select count(*)::int n from action_experiment").fetchone()["n"] == 1
        assert db.execute("select count(*)::int n from action_experiment_outcome").fetchone()["n"] == 1
        db.execute("select set_config('app.tenant_id',%s,true)", (str(tenant_b),))
        assert db.execute("select count(*)::int n from action_experiment").fetchone()["n"] == 0
        assert db.execute("select count(*)::int n from action_experiment_outcome").fetchone()["n"] == 0
        assert db.execute("select has_table_privilege(current_user,'action_experiment_outcome','UPDATE') allowed").fetchone()["allowed"] is False
        assert db.execute("select has_table_privilege(current_user,'action_experiment_outcome','DELETE') allowed").fetchone()["allowed"] is False


def test_verified_outcome_requires_action_and_supported_horizon(experiment_db):
    db, tenant, _, experiment = experiment_db
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""insert into action_experiment_outcome(tenant_id,experiment_id,outcome_kind,outcome,
            metric_name,observed_at,evidence_note) values(%s,%s,'verified_action','improved','acos',now(),'missing action')""",
            (tenant, experiment))
