import datetime as dt
from types import SimpleNamespace

from services.scheduler.runner import Alert, evaluate_alerts, run_ingestion, run_pipeline_cycle


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return self.rows


def test_evaluate_alerts_reports_missing_dataset():
    alerts = evaluate_alerts(FakeConn([]), "tenant-1", expected_datasets=("sales_traffic_asin_daily",))
    assert any(a.kind == "missing" and a.dataset == "sales_traffic_asin_daily" for a in alerts)


def test_evaluate_alerts_reports_failed_latest_run():
    rows = [{"dataset": "sales_traffic_asin_daily", "status": "failed", "started_at": dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc), "finished_at": dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc), "error": "boom"}]
    alerts = evaluate_alerts(FakeConn(rows), "tenant-1", expected_datasets=("sales_traffic_asin_daily",))
    assert Alert("sales_traffic_asin_daily", "failed", "critical", "sales_traffic_asin_daily last run ended failed: boom") in alerts


def test_evaluate_alerts_reports_stale_success():
    rows = [{"dataset": "sales_traffic_asin_daily", "status": "success", "started_at": dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc), "finished_at": dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc), "error": None}]
    alerts = evaluate_alerts(FakeConn(rows), "tenant-1", now=dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc), stale_hours=36, expected_datasets=("sales_traffic_asin_daily",))
    assert any(a.kind == "stale" for a in alerts)


def test_run_ingestion_invokes_ads_and_sales_jobs():
    calls = []

    def ads(tenant_id, dry_run=True):
        calls.append(("ads", tenant_id, dry_run))
        return SimpleNamespace(name="ads")

    def sales(tenant_id, dry_run=True):
        calls.append(("sales", tenant_id, dry_run))
        return SimpleNamespace(name="sales")

    result = run_ingestion("tenant-1", dry_run=True, run_ads=ads, run_sales=sales)
    assert [r.name for r in result] == ["ads", "sales"]
    assert calls == [("ads", "tenant-1", True), ("sales", "tenant-1", True)]


def test_run_pipeline_cycle_invokes_ingestion_then_rules():
    calls = []

    def ads(tenant_id, dry_run=True):
        calls.append(("ads", tenant_id, dry_run))
        return SimpleNamespace(name="ads")

    def sales(tenant_id, dry_run=True):
        calls.append(("sales", tenant_id, dry_run))
        return SimpleNamespace(name="sales")

    def rules(tenant_id):
        calls.append(("rules", tenant_id))
        return SimpleNamespace(name="rules")

    result = run_pipeline_cycle(
        "tenant-1",
        dry_run=True,
        run_ads=ads,
        run_sales=sales,
        run_rules=rules,
    )
    assert [r.name for r in result] == ["ads", "sales", "rules"]
    assert calls == [("ads", "tenant-1", True), ("sales", "tenant-1", True), ("rules", "tenant-1")]
