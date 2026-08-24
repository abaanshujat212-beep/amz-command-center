"""Simple ingestion + rules scheduler runner for local/MVP deployments."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass
from typing import Callable

import psycopg
from psycopg.rows import dict_row

from services.ingest.pipelines import ads_daily, sales_traffic
from services.rules.runner import run_once as run_rules_once

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
DEFAULT_STALE_HOURS = 36


@dataclass(frozen=True)
class Alert:
    dataset: str
    kind: str
    severity: str
    message: str


def _latest_runs(conn, tenant_id: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        select distinct on (dataset)
               dataset, status, started_at, finished_at, error
          from pipeline_run
         where tenant_id = %s
         order by dataset, started_at desc
        """,
        (tenant_id,),
    ).fetchall()
    return {r["dataset"]: r for r in rows}


def evaluate_alerts(
    conn,
    tenant_id: str,
    *,
    now: dt.datetime | None = None,
    stale_hours: int = DEFAULT_STALE_HOURS,
    expected_datasets: tuple[str, ...] = ("sales_traffic_asin_daily", "rules_evaluate"),
) -> list[Alert]:
    now = now or dt.datetime.now(dt.timezone.utc)
    latest = _latest_runs(conn, tenant_id)
    alerts: list[Alert] = []
    expected = set(expected_datasets) | set(ads_daily.DATASETS)
    for dataset in sorted(expected):
        run = latest.get(dataset)
        if run is None:
            alerts.append(Alert(dataset, "missing", "warning", f"{dataset} has never run"))
            continue
        if run["status"] in {"failed", "partial"}:
            alerts.append(
                Alert(dataset, "failed", "critical", f"{dataset} last run ended {run['status']}: {run['error'] or 'no error recorded'}")
            )
            continue
        finished_at = run["finished_at"]
        if finished_at is None:
            alerts.append(Alert(dataset, "running", "warning", f"{dataset} has a run still marked running"))
            continue
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=dt.timezone.utc)
        age_hours = (now - finished_at).total_seconds() / 3600
        if age_hours > stale_hours:
            alerts.append(Alert(dataset, "stale", "warning", f"{dataset} is {age_hours:.1f}h old"))
    return alerts


def run_ingestion(
    tenant_id: str,
    *,
    dry_run: bool = True,
    run_ads: Callable[..., object] = ads_daily.run,
    run_sales: Callable[..., object] = sales_traffic.run,
) -> list[object]:
    return [run_ads(tenant_id, dry_run=dry_run), run_sales(tenant_id, dry_run=dry_run)]


def run_pipeline_cycle(
    tenant_id: str,
    *,
    dry_run: bool = True,
    run_ads: Callable[..., object] = ads_daily.run,
    run_sales: Callable[..., object] = sales_traffic.run,
    run_rules: Callable[..., object] = run_rules_once,
) -> list[object]:
    results = run_ingestion(tenant_id, dry_run=dry_run, run_ads=run_ads, run_sales=run_sales)
    results.append(run_rules(tenant_id))
    return results


def run_once(tenant_id: str, *, dry_run: bool = True, include_rules: bool = True) -> list[Alert]:
    if include_rules:
        run_pipeline_cycle(tenant_id, dry_run=dry_run)
    else:
        run_ingestion(tenant_id, dry_run=dry_run)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return evaluate_alerts(conn, tenant_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MVP ingestion/rules jobs once and print alerts")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--live", action="store_true", help="Call Amazon clients instead of dry-run planning")
    parser.add_argument("--skip-rules", action="store_true", help="Only run ingestion jobs")
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    alerts = run_once(args.tenant_id, dry_run=not args.live, include_rules=not args.skip_rules)
    for alert in alerts:
        print(f"{alert.severity.upper()} {alert.dataset} {alert.kind}: {alert.message}")


if __name__ == "__main__":
    main()
