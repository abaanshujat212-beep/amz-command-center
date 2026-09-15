import os
import uuid
from decimal import Decimal

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP",
    "postgresql://axaty_app:axaty_app@localhost:5432/axaty",
)


def _create_tenant(admin: psycopg.Connection, tenant_id: uuid.UUID, slug: str) -> None:
    admin.execute(
        "insert into tenant(id, name, slug) values (%s, %s, %s)",
        (tenant_id, slug, slug),
    )
    admin.execute("insert into tenant_settings(tenant_id) values (%s)", (tenant_id,))


def test_guardrail_defaults_are_persisted_and_conservative():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        _create_tenant(admin, tenant_id, f"guard-default-{tenant_id}")
        try:
            row = admin.execute(
                "select automation_enabled, dry_run, max_change_pct, cooldown_days,"
                " max_budget_increase_per_day, blast_radius_pct, max_data_age_hours,"
                " settlement_lag_days from tenant_settings where tenant_id = %s",
                (tenant_id,),
            ).fetchone()
            assert row == (
                False,
                True,
                Decimal("0.2500"),
                3,
                Decimal("50.00"),
                Decimal("0.3000"),
                48,
                3,
            )
        finally:
            admin.execute("delete from tenant where id = %s", (tenant_id,))


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ("max_change_pct", 0),
        ("max_change_pct", 1.01),
        ("cooldown_days", -1),
        ("cooldown_days", 91),
        ("max_budget_increase_per_day", -0.01),
        ("blast_radius_pct", 0),
        ("blast_radius_pct", 1.01),
        ("max_data_age_hours", 0),
        ("max_data_age_hours", 721),
        ("settlement_lag_days", -1),
        ("settlement_lag_days", 31),
        ("max_daily_budget", -0.01),
        ("max_changes_per_day", -1),
    ],
)
def test_invalid_guardrail_bounds_are_rejected(assignment, value):
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        _create_tenant(admin, tenant_id, f"guard-invalid-{tenant_id}")
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    f"update tenant_settings set {assignment} = %s where tenant_id = %s",
                    (value, tenant_id),
                )
        finally:
            admin.execute("delete from tenant where id = %s", (tenant_id,))


def test_minimum_bid_cannot_exceed_maximum_bid():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        _create_tenant(admin, tenant_id, f"guard-bids-{tenant_id}")
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    "update tenant_settings set min_bid = 6, max_bid = 5 where tenant_id = %s",
                    (tenant_id,),
                )
        finally:
            admin.execute("delete from tenant where id = %s", (tenant_id,))


def test_guardrail_settings_remain_tenant_isolated():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        _create_tenant(admin, tenant_a, f"guard-a-{tenant_a}")
        _create_tenant(admin, tenant_b, f"guard-b-{tenant_b}")
    try:
        with psycopg.connect(APP_URL) as conn, conn.transaction():
            conn.execute("select set_tenant(%s)", (tenant_a,))
            assert conn.execute("select count(*) from tenant_settings").fetchone()[0] == 1
            result = conn.execute(
                "update tenant_settings set dry_run = false where tenant_id = %s",
                (tenant_b,),
            )
            assert result.rowcount == 0
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            assert admin.execute(
                "select dry_run from tenant_settings where tenant_id = %s",
                (tenant_b,),
            ).fetchone()[0]
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute("delete from tenant where id = any(%s)", ([tenant_a, tenant_b],))
