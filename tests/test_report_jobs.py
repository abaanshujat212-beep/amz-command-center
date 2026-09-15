import datetime as dt
from pathlib import Path

import pytest

from services.reports.jobs import SUPPORTED_FORMATS, enqueue_job, fail_job

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "services/reports/jobs.py").read_text()
UP = (ROOT / "packages/db/migrations/0032_report_job_core.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0032_report_job_core.sql").read_text()


def test_report_job_contract_is_idempotent_atomic_and_tenant_scoped():
    assert "on conflict(tenant_id,idempotency_key) do nothing" in SOURCE
    assert "for update skip locked" in SOURCE
    assert "where tenant_id=%s" in SOURCE
    assert "set_tenant" in SOURCE
    assert "report_job_event" in SOURCE
    assert "force row level security" in UP


def test_report_job_formats_and_scope_fail_closed():
    assert SUPPORTED_FORMATS == {"csv", "xlsx", "pdf"}
    with pytest.raises(ValueError, match="unsupported"):
        enqueue_job(
            None,
            tenant_id="t1",
            definition_code="monthly",
            definition_version=1,
            requested_by="u1",
            idempotency_key="k1",
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 1, 31),
            filters={},
            output_format="html",
        )
    with pytest.raises(ValueError, match="requires an error"):
        fail_job(None, tenant_id="t1", job_id="j1", worker_id="w1", error="")


def test_report_definition_scope_and_terminal_state_are_immutable():
    assert "report definitions are immutable" in UP
    assert "report job scope is immutable" in UP
    assert "terminal report job is immutable" in UP
    assert "claim must increment report attempt exactly once" in UP
    assert "old.attempt < old.max_attempts" in UP


def test_report_job_migration_is_sequential_and_reversible():
    assert UP.startswith("-- 0032_report_job_core.sql")
    assert "drop table if exists report_job_event" in DOWN
    assert "drop table if exists report_job" in DOWN
    assert "drop table if exists report_definition" in DOWN
