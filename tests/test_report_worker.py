import datetime as dt
from pathlib import Path

import pytest

from services.reports.worker import CAMPAIGN_COLUMNS, _source_query

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0056_governed_report_execution.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0056_governed_report_execution.sql").read_text()
WORKER = (ROOT / "services/reports/worker.py").read_text()


def snapshot():
    return {
        "source_contract": "mart-ppc-campaign-daily-v1",
        "definition": {"columns": list(CAMPAIGN_COLUMNS)},
    }


def test_source_contract_reads_mart_without_recalculating_metrics():
    sql, filter_values = _source_query(
        snapshot(), {"campaign_status": "enabled", "targeting_type": "manual"}
    )
    assert "from mart_ppc_campaign_daily" in sql
    assert "order by report_date,campaign_id" in sql
    assert " sum(" not in sql.lower()
    assert " case " not in sql.lower()
    assert filter_values == ["enabled", "manual"]


def test_source_contract_filters_fail_closed():
    with pytest.raises(ValueError, match="unsupported report filters"):
        _source_query(snapshot(), {"tenant_id": "another-tenant"})
    with pytest.raises(ValueError, match="registered source contract"):
        _source_query({**snapshot(), "definition": {"columns": ["report_date"]}}, {})
    with pytest.raises(ValueError, match="unsupported report source contract"):
        _source_query({"source_contract": "raw-table", "definition": {}}, {})


def test_execution_contract_is_observable_reversible_and_uses_tenant_retention():
    assert UP.startswith("-- 0056_governed_report_execution.sql")
    assert "progress_current" in UP and "heartbeat_at" in UP
    assert "mart-ppc-campaign-daily-v1" in UP
    assert "drop column if exists progress_current" in DOWN
    assert "select set_tenant(%s)" in WORKER
    assert "retention_days" in WORKER
    assert "LocalPrivateArtifactStore" in WORKER
    assert "render_claimed_job" in WORKER


def test_date_scope_parameters_are_not_interpolated():
    sql, values = _source_query(snapshot(), {})
    params = [dt.date(2026, 1, 1), dt.date(2026, 1, 31), *values]
    assert "report_date between %s and %s" in sql
    assert params == [dt.date(2026, 1, 1), dt.date(2026, 1, 31)]
