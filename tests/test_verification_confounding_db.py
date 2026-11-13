import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _tenant(conn, name):
    tenant_id = uuid.uuid4()
    conn.execute("select set_tenant(%s)", (tenant_id,))
    conn.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, name, f"{name}-{tenant_id}"))
    return tenant_id


def _action(conn, tenant_id, *, action_id=None, status="applied", applied_at=None, rolled_back_at=None):
    action_id = action_id or uuid.uuid4()
    conn.execute("select set_tenant(%s)", (tenant_id,))
    conn.execute(
        """insert into action(id,tenant_id,entity_type,entity_id,action_type,after_value,
           status,idempotency_key,applied_at,rolled_back_at)
           values(%s,%s,'keyword','K-1','set_bid','{\"value\":1.1}',%s,%s,%s,%s)""",
        (action_id, tenant_id, status, str(action_id), applied_at, rolled_back_at),
    )
    return action_id


def test_confounded_evidence_uses_stored_half_open_utc_windows_and_keeps_snapshot_immutable():
    focal_tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    today = now.date()
    before_start, boundary, after_end = today - dt.timedelta(days=10), today - dt.timedelta(days=5), today - dt.timedelta(days=1)
    focal_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        for tenant_id, name in ((focal_tenant, "confounder"), (other_tenant, "other-confounder")):
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, name, str(tenant_id)))
        _action(admin, focal_tenant, action_id=focal_id, applied_at=dt.datetime.combine(boundary, dt.time(), dt.timezone.utc), rolled_back_at=dt.datetime.combine(boundary, dt.time(2), dt.timezone.utc))
        _action(admin, focal_tenant, applied_at=dt.datetime.combine(before_start + dt.timedelta(days=1), dt.time(12), dt.timezone.utc))
        _action(admin, focal_tenant, applied_at=dt.datetime.combine(boundary, dt.time(), dt.timezone.utc))
        _action(admin, focal_tenant, status="rolled_back", applied_at=dt.datetime.combine(before_start - dt.timedelta(days=20), dt.time(), dt.timezone.utc), rolled_back_at=dt.datetime.combine(boundary + dt.timedelta(days=1), dt.time(3), dt.timezone.utc))
        _action(admin, other_tenant, applied_at=dt.datetime.combine(boundary + dt.timedelta(days=1), dt.time(), dt.timezone.utc))
        admin.execute("select set_tenant(%s)", (focal_tenant,))
        admin.execute(
            """insert into action_verification_snapshot(
               tenant_id,action_id,horizon_days,status,outcome,metric_keys,baseline_metrics,observed_metrics,
               window_before_start,window_before_end,window_after_start,window_after_end,data_through,completed_at)
               values(%s,%s,7,'COMPLETE','improved','[]','{}','{}',%s,%s,%s,%s,%s,now())""",
            (focal_tenant, focal_id, before_start, boundary, boundary, after_end, after_end),
        )
        for source, source_ref, observed_at, expires_at in (
            ("manual", "manual-expired-ttl", dt.datetime.combine(before_start + dt.timedelta(days=2), dt.time(9), dt.timezone.utc), now - dt.timedelta(days=2)),
            ("amazon_native", "native-at-boundary", dt.datetime.combine(boundary, dt.time(), dt.timezone.utc), now - dt.timedelta(days=1)),
            ("amazon_native", "native-after", dt.datetime.combine(boundary + dt.timedelta(days=2), dt.time(9), dt.timezone.utc), now + dt.timedelta(days=1)),
            ("manual", "native-after-end", dt.datetime.combine(after_end, dt.time(), dt.timezone.utc), now + dt.timedelta(days=1)),
        ):
            admin.execute(
                """insert into entity_change_signal(tenant_id,entity_type,entity_id,source,change_kind,
                   source_ref,observed_at,expires_at) values(%s,'keyword','K-1',%s,'bid',%s,%s,%s)""",
                (focal_tenant, source, source_ref, observed_at, max(expires_at, observed_at + dt.timedelta(hours=1))),
            )
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (focal_tenant,))
                result = app.execute(
                    "select * from verification_confounding_evidence(%s,%s,7)", (focal_tenant, focal_id)
                ).fetchone()
                assert result[0] == "CONFOUNDED"
                assert result[2] == 7
                assert result[3] is False
                evidence = result[1]
                assert {row["window"] for row in evidence if row["source"] == "manual"} == {"baseline"}
                assert "manual-expired-ttl" in {row["source_ref"] for row in evidence}
                assert "native-at-boundary" in {row["source_ref"] for row in evidence}
                assert "native-after-end" not in {row["source_ref"] for row in evidence}
                assert any(row["change_kind"] == "rollback:set_bid" and row["action_id"] == str(focal_id) for row in evidence)
                assert app.execute("select status,outcome from action_verification_snapshot where tenant_id=%s and action_id=%s", (focal_tenant, focal_id)).fetchone() == ("COMPLETE", "improved")
                # RLS prevents a caller from asking the function to inspect another tenant.
                assert app.execute("select * from verification_confounding_evidence(%s,%s,7)", (other_tenant, focal_id)).fetchone() is None
        finally:
            for tenant_id in (focal_tenant, other_tenant):
                admin.execute("select set_tenant(%s)", (tenant_id,))
                admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.commit()


def test_complete_clean_windows_report_no_recorded_changes_and_incomplete_windows_stay_pending():
    tenant_id, complete_id, pending_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    today = dt.datetime.now(dt.timezone.utc).date()
    with psycopg.connect(ADMIN_URL) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        conn.execute("insert into tenant(id,name,slug) values(%s,'clean-confounder',%s)", (tenant_id, str(tenant_id)))
        for action_id, status, outcome in ((complete_id, "COMPLETE", "neutral"), (pending_id, "INSUFFICIENT_DATA", None)):
            _action(conn, tenant_id, action_id=action_id, applied_at=dt.datetime.now(dt.timezone.utc))
            conn.execute(
                """insert into action_verification_snapshot(
                   tenant_id,action_id,horizon_days,status,outcome,metric_keys,baseline_metrics,observed_metrics,
                   window_before_start,window_before_end,window_after_start,window_after_end,reason_code,completed_at)
                   values(%s,%s,1,%s,%s,'[]','{}','{}',%s,%s,%s,%s,%s,%s)""",
                (tenant_id, action_id, status, outcome, today-dt.timedelta(days=2), today-dt.timedelta(days=1), today-dt.timedelta(days=1), today, None if status == "COMPLETE" else "WINDOW_NOT_MATURE", dt.datetime.now(dt.timezone.utc) if status == "COMPLETE" else None),
            )
        conn.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                complete = app.execute("select * from verification_confounding_evidence(%s,%s,1)", (tenant_id, complete_id)).fetchone()
                pending = app.execute("select * from verification_confounding_evidence(%s,%s,1)", (tenant_id, pending_id)).fetchone()
                assert complete[:3] == ("NO_RECORDED_CHANGES", [], 0)
                assert pending[:3] == ("PENDING", [], 0)
        finally:
            conn.execute("select set_tenant(%s)", (tenant_id,))
            conn.execute("delete from tenant where id=%s", (tenant_id,))
            conn.commit()


def test_confounder_evidence_is_bounded_and_reports_truncation():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=2)
    with psycopg.connect(ADMIN_URL) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        conn.execute("insert into tenant(id,name,slug) values(%s,'many-confounders',%s)", (tenant_id, str(tenant_id)))
        _action(conn, tenant_id, action_id=action_id, applied_at=dt.datetime.combine(start, dt.time(), dt.timezone.utc))
        conn.execute(
            """insert into action_verification_snapshot(
               tenant_id,action_id,horizon_days,status,outcome,metric_keys,baseline_metrics,observed_metrics,
               window_before_start,window_before_end,window_after_start,window_after_end,data_through,completed_at)
               values(%s,%s,1,'COMPLETE','neutral','[]','{}','{}',%s,%s,%s,%s,%s,now())""",
            (tenant_id, action_id, start-dt.timedelta(days=1), start, start, start+dt.timedelta(days=1), start+dt.timedelta(days=1)),
        )
        for index in range(25):
            observed_at = dt.datetime.combine(start, dt.time(), dt.timezone.utc) + dt.timedelta(minutes=index * 40)
            conn.execute(
                """insert into entity_change_signal(tenant_id,entity_type,entity_id,source,change_kind,
                   source_ref,observed_at,expires_at) values(%s,'keyword','K-1','manual','bid',%s,%s,%s)""",
                (tenant_id, f"signal-{index}", observed_at, observed_at+dt.timedelta(hours=1)),
            )
        conn.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                result = app.execute("select * from verification_confounding_evidence(%s,%s,1)", (tenant_id, action_id)).fetchone()
                assert result[0] == "CONFOUNDED"
                assert result[2] == 25
                assert len(result[1]) == 20
                assert result[3] is True
        finally:
            conn.execute("select set_tenant(%s)", (tenant_id,))
            conn.execute("delete from tenant where id=%s", (tenant_id,))
            conn.commit()
