import datetime as dt
from types import SimpleNamespace

from services.ingest.pipelines import ads_daily, sales_traffic
from services.scheduler.runner import (
    Alert,
    CatchUpPlan,
    build_catch_up_plan,
    evaluate_alerts,
    replay_catch_up_plan,
    run_ingestion,
    run_pipeline_cycle,
)


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
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


def test_build_catch_up_plan_reports_missing_days_in_rolling_window():
    rows = [
        {"date_from": dt.date(2026, 8, 21), "date_to": dt.date(2026, 8, 21)},
        {"date_from": dt.date(2026, 8, 23), "date_to": dt.date(2026, 8, 23)},
    ]
    plans = build_catch_up_plan(
        FakeConn(rows),
        "tenant-1",
        today=dt.date(2026, 8, 24),
        days=3,
        datasets=("sales_traffic_asin_daily",),
    )
    assert len(plans) == 1
    assert plans[0].dataset == "sales_traffic_asin_daily"
    assert plans[0].start == dt.date(2026, 8, 22)
    assert plans[0].end == dt.date(2026, 8, 22)
    assert plans[0].dates == (dt.date(2026, 8, 22),)
    assert plans[0].days == 1


def test_build_catch_up_plan_defaults_to_sales_and_ads_datasets():
    plans = build_catch_up_plan(FakeConn([]), "tenant-1", today=dt.date(2026, 8, 24), days=1)
    datasets = {plan.dataset for plan in plans}
    assert sales_traffic.DATASET in datasets
    assert set(ads_daily.DATASETS).issubset(datasets)


def test_build_catch_up_plan_skips_complete_dataset():
    rows = [{"date_from": dt.date(2026, 8, 21), "date_to": dt.date(2026, 8, 23)}]
    plans = build_catch_up_plan(
        FakeConn(rows),
        "tenant-1",
        today=dt.date(2026, 8, 24),
        days=3,
        datasets=("sales_traffic_asin_daily",),
    )
    assert plans == []


def test_replay_catch_up_plan_replays_supported_sales_traffic_window():
    calls = []

    def run_sales(tenant_id, dry_run=True, today=None):
        calls.append((tenant_id, dry_run, today))
        return SimpleNamespace(name="sales")

    result = replay_catch_up_plan(
        "tenant-1",
        [CatchUpPlan(sales_traffic.DATASET, dt.date(2026, 8, 22), dt.date(2026, 8, 22), (dt.date(2026, 8, 22),))],
        dry_run=True,
        run_sales=run_sales,
    )
    assert calls == [("tenant-1", True, dt.date(2026, 8, 23))]
    assert result[0].dataset == sales_traffic.DATASET
    assert result[0].planned_days == 1
    assert result[0].replayed is True
    assert result[0].dry_run is True


def test_replay_catch_up_plan_replays_supported_ads_dataset_window():
    calls = []

    def run_ads(tenant_id, dry_run=True, today=None, datasets=None):
        calls.append((tenant_id, dry_run, today, datasets))
        return SimpleNamespace(name="ads")

    result = replay_catch_up_plan(
        "tenant-1",
        [CatchUpPlan("ads_sp_campaign_daily", dt.date(2026, 8, 22), dt.date(2026, 8, 22), (dt.date(2026, 8, 22),))],
        dry_run=True,
        run_ads=run_ads,
    )
    assert calls == [("tenant-1", True, dt.date(2026, 8, 23), ("ads_sp_campaign_daily",))]
    assert result[0].dataset == "ads_sp_campaign_daily"
    assert result[0].planned_days == 1
    assert result[0].replayed is True
    assert result[0].dry_run is True


def test_replay_catch_up_plan_leaves_unknown_dataset_planned_only():
    calls = []

    def run_ads(tenant_id, dry_run=True, today=None, datasets=None):
        calls.append((tenant_id, dry_run, today, datasets))

    result = replay_catch_up_plan(
        "tenant-1",
        [CatchUpPlan("unknown_daily", dt.date(2026, 8, 22), dt.date(2026, 8, 22), (dt.date(2026, 8, 22),))],
        dry_run=True,
        run_ads=run_ads,
    )
    assert calls == []
    assert result[0].dataset == "unknown_daily"
    assert result[0].planned_days == 1
    assert result[0].replayed is False


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
