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
DEFAULT_CATCH_UP_DAYS = 14
DEFAULT_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class Alert:
    dataset: str
    kind: str
    severity: str
    message: str


@dataclass(frozen=True)
class CatchUpPlan:
    dataset: str
    start: dt.date
    end: dt.date
    dates: tuple[dt.date, ...]

    @property
    def days(self) -> int:
        return len(self.dates)


@dataclass(frozen=True)
class CatchUpReplayResult:
    dataset: str
    planned_days: int
    replayed: bool
    dry_run: bool


@dataclass(frozen=True)
class RunHistoryItem:
    dataset: str
    status: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    rows_loaded: int | None
    error: str | None

    @property
    def finished(self) -> bool:
        return self.finished_at is not None


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


def load_run_history(conn, tenant_id: str, *, limit: int = DEFAULT_HISTORY_LIMIT) -> list[RunHistoryItem]:
    if limit < 1:
        raise ValueError("history limit must be at least 1")
    rows = conn.execute(
        """
        select dataset, status, started_at, finished_at, rows_loaded, error
          from pipeline_run
         where tenant_id = %s
         order by started_at desc
         limit %s
        """,
        (tenant_id, limit),
    ).fetchall()
    return [
        RunHistoryItem(
            dataset=row["dataset"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            rows_loaded=row["rows_loaded"],
            error=row["error"],
        )
        for row in rows
    ]


def _successful_run_dates(conn, tenant_id: str, dataset: str, start: dt.date, end: dt.date) -> set[dt.date]:
    rows = conn.execute(
        """
        select date_from, date_to
          from pipeline_run
         where tenant_id = %s
           and dataset = %s
           and status = 'success'
           and date_from is not null
           and date_to is not null
           and date_to >= %s
           and date_from <= %s
        """,
        (tenant_id, dataset, start, end),
    ).fetchall()
    dates: set[dt.date] = set()
    for row in rows:
        current = max(row["date_from"], start)
        last = min(row["date_to"], end)
        while current <= last:
            dates.add(current)
            current += dt.timedelta(days=1)
    return dates


def _date_range(start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
    if start > end:
        return ()
    return tuple(start + dt.timedelta(days=i) for i in range((end - start).days + 1))


def build_catch_up_plan(
    conn,
    tenant_id: str,
    *,
    today: dt.date | None = None,
    days: int = DEFAULT_CATCH_UP_DAYS,
    datasets: tuple[str, ...] | None = None,
) -> list[CatchUpPlan]:
    """Find missing successful pipeline days in the recent rolling window."""
    if days < 1:
        raise ValueError("catch-up days must be at least 1")
    today = today or dt.date.today()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    expected = set(_date_range(start, end))
    selected = datasets or (sales_traffic.DATASET, *ads_daily.DATASETS.keys())
    plans: list[CatchUpPlan] = []
    for dataset in selected:
        present = _successful_run_dates(conn, tenant_id, dataset, start, end)
        missing = tuple(sorted(expected - present))
        if missing:
            plans.append(CatchUpPlan(dataset, missing[0], missing[-1], missing))
    return plans


def replay_catch_up_plan(
    tenant_id: str,
    plans: list[CatchUpPlan],
    *,
    dry_run: bool = True,
    run_ads: Callable[..., object] = ads_daily.run,
    run_sales: Callable[..., object] = sales_traffic.run,
) -> list[CatchUpReplayResult]:
    """Replay supported catch-up plans through existing pipeline boundaries."""
    results: list[CatchUpReplayResult] = []
    for plan in plans:
        replayed = False
        if plan.dataset == sales_traffic.DATASET:
            run_sales(tenant_id, dry_run=dry_run, today=plan.end + dt.timedelta(days=1))
            replayed = True
        elif plan.dataset in ads_daily.DATASETS:
            run_ads(
                tenant_id,
                dry_run=dry_run,
                today=plan.end + dt.timedelta(days=1),
                datasets=(plan.dataset,),
            )
            replayed = True
        results.append(
            CatchUpReplayResult(
                dataset=plan.dataset,
                planned_days=plan.days,
                replayed=replayed,
                dry_run=dry_run,
            )
        )
    return results


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
    parser.add_argument("--show-catch-up", action="store_true", help="Print missing successful days in the rolling catch-up window")
    parser.add_argument("--replay-catch-up", action="store_true", help="Replay supported missing days in the catch-up window")
    parser.add_argument("--show-history", action="store_true", help="Print recent pipeline run history")
    parser.add_argument("--history-limit", type=int, default=DEFAULT_HISTORY_LIMIT)
    parser.add_argument("--catch-up-days", type=int, default=DEFAULT_CATCH_UP_DAYS)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    if args.show_history:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            for item in load_run_history(conn, args.tenant_id, limit=args.history_limit):
                finished = item.finished_at.isoformat() if item.finished_at else "running"
                error = f" error={item.error}" if item.error else ""
                print(
                    f"RUN_HISTORY {item.dataset} status={item.status} started={item.started_at.isoformat()} finished={finished} rows={item.rows_loaded}{error}"
                )
    if args.show_catch_up or args.replay_catch_up:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            plans = build_catch_up_plan(conn, args.tenant_id, days=args.catch_up_days)
        for plan in plans:
            print(f"CATCH_UP {plan.dataset} {plan.start}..{plan.end} missing_days={plan.days}")
        if args.replay_catch_up:
            for result in replay_catch_up_plan(args.tenant_id, plans, dry_run=not args.live):
                status = "replayed" if result.replayed else "planned_only"
                print(f"CATCH_UP_REPLAY {result.dataset} {status} days={result.planned_days} dry_run={result.dry_run}")
    alerts = run_once(args.tenant_id, dry_run=not args.live, include_rules=not args.skip_rules)
    for alert in alerts:
        print(f"{alert.severity.upper()} {alert.dataset} {alert.kind}: {alert.message}")


if __name__ == "__main__":
    main()
