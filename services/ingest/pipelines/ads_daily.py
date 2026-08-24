"""First Ads ingestion orchestration: Sponsored Products daily reports."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from services.ingest.clients.ads_api import AdsClient, AdsCredentials
from services.ingest.security.vault import unseal

BACKFILL_DAYS = 95
SETTLEMENT_LAG_DAYS = 3
REINGEST_DAYS = 14
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


@dataclass(frozen=True)
class ReportSpec:
    kind: str
    group_by: tuple[str, ...] = ()


DATASETS: dict[str, ReportSpec] = {
    "ads_sp_campaign_daily": ReportSpec("spCampaigns", ("campaign",)),
    "ads_sp_placement_daily": ReportSpec("spCampaigns", ("campaign", "campaignPlacement")),
    "ads_sp_ad_group_daily": ReportSpec("spAdGroups", ("adGroup",)),
    "ads_sp_keyword_daily": ReportSpec("spTargeting", ("targeting",)),
    "ads_sp_search_term_daily": ReportSpec("spSearchTerm", ("searchTerm",)),
    "ads_sp_advertised_product_daily": ReportSpec("spAdvertisedProduct", ("advertiser",)),
    "ads_sp_purchased_product_daily": ReportSpec("spPurchasedProduct", ("asin",)),
}


@dataclass(frozen=True)
class Window:
    start: dt.date
    end: dt.date


@dataclass(frozen=True)
class AdsConnection:
    region: str
    client_id: str
    client_secret: str
    refresh_token: str
    profile_id: int | None


@dataclass(frozen=True)
class ReportRequest:
    dataset: str
    spec: ReportSpec
    date: dt.date


@dataclass
class DatasetResult:
    dataset: str
    requested: int = 0
    succeeded: int = 0
    failed: int = 0
    report_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    tenant_id: str
    dry_run: bool
    datasets: list[DatasetResult]

    @property
    def succeeded(self) -> int:
        return sum(d.succeeded for d in self.datasets)

    @property
    def failed(self) -> int:
        return sum(d.failed for d in self.datasets)


class AdsReportClient(Protocol):
    def create_report(
        self,
        report_kind: str,
        start_date: dt.date,
        end_date: dt.date,
        group_by: tuple[str, ...] = (),
    ) -> str: ...

    def wait_for_report(self, report_id: str, timeout_s: int = 1800) -> str: ...

    def download_report(self, url: str) -> bytes: ...


def plan_dates(
    last_complete: dt.date | None,
    today: dt.date | None = None,
    backfill_days: int = BACKFILL_DAYS,
    reingest_days: int = REINGEST_DAYS,
) -> list[dt.date]:
    today = today or dt.date.today()
    newest = today - dt.timedelta(days=1)
    oldest_available = today - dt.timedelta(days=backfill_days)

    if last_complete is not None and last_complete >= newest:
        return []

    if last_complete is None:
        start = oldest_available
    else:
        start = min(
            last_complete + dt.timedelta(days=1),
            newest - dt.timedelta(days=reingest_days - 1),
        )
        start = max(start, oldest_available)

    if start > newest:
        return []
    span = (newest - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(span)]


def find_gaps(expected: list[dt.date], present: set[dt.date]) -> list[dt.date]:
    return sorted(d for d in expected if d not in present)


def rules_safe_date(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=SETTLEMENT_LAG_DAYS)


def requests_for_dataset(
    dataset: str,
    last_complete: dt.date | None,
    today: dt.date | None = None,
) -> list[ReportRequest]:
    spec = DATASETS[dataset]
    return [ReportRequest(dataset, spec, day) for day in plan_dates(last_complete, today=today)]


def _run_status(result: DatasetResult) -> str:
    if result.failed and result.succeeded:
        return "partial"
    if result.failed:
        return "failed"
    return "success"


def load_ads_connection(conn, tenant_id: str) -> AdsConnection:
    row = conn.execute(
        """
        select c.region,
               c.refresh_token_encrypted,
               p.profile_id
          from amazon_connection c
          left join ads_profile p
            on p.connection_id = c.id
           and p.tenant_id = c.tenant_id
         where c.tenant_id = %s
           and c.provider = 'ads_api'
           and c.status = 'active'
         order by p.created_at nulls last
         limit 1
        """,
        (tenant_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"tenant {tenant_id} has no active Ads API connection")
    if row["refresh_token_encrypted"] is None:
        raise RuntimeError(f"tenant {tenant_id} Ads API connection has no refresh token")
    client_id = os.environ.get("ADS_CLIENT_ID")
    client_secret = os.environ.get("ADS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("ADS_CLIENT_ID and ADS_CLIENT_SECRET must be set")
    return AdsConnection(
        region=row["region"],
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=unseal(bytes(row["refresh_token_encrypted"])),
        profile_id=row["profile_id"],
    )


def read_watermark(conn, tenant_id: str, dataset: str) -> dt.date | None:
    row = conn.execute(
        "select last_complete_date from sync_watermark where tenant_id = %s and dataset = %s",
        (tenant_id, dataset),
    ).fetchone()
    return None if row is None else row["last_complete_date"]


def start_pipeline_run(conn, tenant_id: str, dataset: str, dates: list[dt.date]) -> uuid.UUID:
    date_from = min(dates) if dates else None
    date_to = max(dates) if dates else None
    row = conn.execute(
        """
        insert into pipeline_run (tenant_id, dataset, date_from, date_to, status)
        values (%s, %s, %s, %s, 'running')
        returning id
        """,
        (tenant_id, dataset, date_from, date_to),
    ).fetchone()
    return row["id"]


def finish_pipeline_run(conn, run_id: uuid.UUID, result: DatasetResult) -> None:
    conn.execute(
        """
        update pipeline_run
           set finished_at = now(),
               status = %s,
               rows_loaded = %s,
               error = %s,
               detail = %s
         where id = %s
        """,
        (
            _run_status(result),
            result.succeeded,
            "\n".join(result.errors) or None,
            psycopg.types.json.Jsonb(
                {
                    "requested": result.requested,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "report_ids": result.report_ids,
                    "errors": result.errors,
                }
            ),
            run_id,
        ),
    )


def update_watermark(conn, tenant_id: str, dataset: str, completed_dates: list[dt.date]) -> None:
    if not completed_dates:
        return
    last_complete = max(completed_dates)
    conn.execute(
        """
        insert into sync_watermark (tenant_id, dataset, last_complete_date, last_attempt_at, last_status)
        values (%s, %s, %s, now(), 'success')
        on conflict (tenant_id, dataset) do update set
            last_complete_date = greatest(sync_watermark.last_complete_date, excluded.last_complete_date),
            last_attempt_at = excluded.last_attempt_at,
            last_status = excluded.last_status
        """,
        (tenant_id, dataset, last_complete),
    )


def run_requests(
    client: AdsReportClient,
    requests: Iterable[ReportRequest],
    *,
    dry_run: bool = True,
) -> DatasetResult:
    requests = list(requests)
    dataset = requests[0].dataset if requests else "unknown"
    result = DatasetResult(dataset=dataset, requested=len(requests))
    if dry_run:
        result.succeeded = len(requests)
        return result

    for req in requests:
        try:
            report_id = client.create_report(req.spec.kind, req.date, req.date, req.spec.group_by)
            download_url = client.wait_for_report(report_id)
            client.download_report(download_url)
            result.report_ids.append(report_id)
            result.succeeded += 1
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{req.dataset} {req.date}: {exc}")
    return result


def run(
    tenant_id: str,
    dry_run: bool = True,
    *,
    today: dt.date | None = None,
    datasets: Iterable[str] | None = None,
    client_factory: Callable[[AdsConnection], AdsReportClient] | None = None,
) -> RunResult:
    selected = list(datasets or DATASETS)
    unknown = sorted(set(selected) - set(DATASETS))
    if unknown:
        raise ValueError(f"unknown Ads dataset(s): {unknown}")

    results: list[DatasetResult] = []
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        ads_connection = None if dry_run and client_factory is None else load_ads_connection(conn, tenant_id)
        client = None
        if ads_connection is not None:
            client = (client_factory or _default_client)(ads_connection)

        for dataset in selected:
            last_complete = read_watermark(conn, tenant_id, dataset)
            requests = requests_for_dataset(dataset, last_complete, today=today)
            run_id = start_pipeline_run(conn, tenant_id, dataset, [r.date for r in requests])
            result = run_requests(client, requests, dry_run=dry_run) if client else run_requests(_DryClient(), requests, dry_run=True)
            result.dataset = dataset
            finish_pipeline_run(conn, run_id, result)
            if result.failed == 0:
                update_watermark(conn, tenant_id, dataset, [r.date for r in requests])
            results.append(result)
        conn.commit()
    return RunResult(tenant_id=tenant_id, dry_run=dry_run, datasets=results)


def _default_client(connection: AdsConnection) -> AdsClient:
    return AdsClient(
        AdsCredentials(
            connection.client_id,
            connection.client_secret,
            connection.refresh_token,
            connection.profile_id,
        ),
        tenant_id=None,
        region=connection.region,
    )


class _DryClient:
    def create_report(self, report_kind, start_date, end_date, group_by=()):
        return f"dry-{report_kind}-{start_date}"

    def wait_for_report(self, report_id: str, timeout_s: int = 1800) -> str:
        return f"dry://{report_id}"

    def download_report(self, url: str) -> bytes:
        return b""
