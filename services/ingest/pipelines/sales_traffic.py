"""SP-API Sales & Traffic ingestion at CHILD ASIN daily grain."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from services.ingest.clients.sp_api import SALES_AND_TRAFFIC, SpApiClient, SpApiCredentials
from services.ingest.security.vault import seal, unseal

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
BACKFILL_DAYS = 730
REINGEST_DAYS = 14
DATASET = "sales_traffic_asin_daily"
RAW_TABLE = "raw_sales_traffic_asin_daily"
REPORT_OPTIONS = {"dateGranularity": "DAY", "asinGranularity": "CHILD"}


@dataclass(frozen=True)
class SpConnection:
    connection_id: str
    region: str
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class ReportRequest:
    date: dt.date


@dataclass
class RunResult:
    tenant_id: str
    dry_run: bool
    requested: int = 0
    succeeded: int = 0
    failed: int = 0
    rows_loaded: int = 0
    report_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SalesTrafficClient(Protocol):
    def create_report(self, report_type: str, start: dt.date, end: dt.date, report_options: dict | None = None) -> str: ...
    def wait_for_report(self, report_id: str, timeout_s: int = 3600) -> str: ...
    def download_report(self, document_id: str) -> bytes: ...


def plan_dates(last_complete: dt.date | None, today: dt.date | None = None, backfill_days: int = BACKFILL_DAYS, reingest_days: int = REINGEST_DAYS) -> list[dt.date]:
    today = today or dt.date.today()
    newest = today - dt.timedelta(days=1)
    oldest_available = today - dt.timedelta(days=backfill_days)
    if last_complete is not None and last_complete >= newest:
        return []
    if last_complete is None:
        start = oldest_available
    else:
        start = min(last_complete + dt.timedelta(days=1), newest - dt.timedelta(days=reingest_days - 1))
        start = max(start, oldest_available)
    if start > newest:
        return []
    return [start + dt.timedelta(days=i) for i in range((newest - start).days + 1)]


def parse_money(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("amount")
    return value


def parse_report_payload(payload: bytes) -> list[dict[str, Any]]:
    if not payload:
        return []
    try:
        text = gzip.decompress(payload).decode("utf-8")
    except gzip.BadGzipFile:
        text = payload.decode("utf-8")
    doc = json.loads(text)
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict):
        if isinstance(doc.get("salesAndTrafficByAsin"), list):
            return [r for r in doc["salesAndTrafficByAsin"] if isinstance(r, dict)]
        if isinstance(doc.get("records"), list):
            return [r for r in doc["records"] if isinstance(r, dict)]
    raise ValueError("Sales & Traffic payload must contain salesAndTrafficByAsin[] or records[]")


def _nested(row: dict[str, Any], *path: str) -> Any:
    value: Any = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def normalize_row(row: dict[str, Any], fallback_date: dt.date) -> tuple[dt.date, str, dict[str, Any]]:
    asin = row.get("childAsin") or row.get("child_asin") or row.get("asin")
    if not asin:
        asin = _nested(row, "trafficByAsin", "childAsin") or _nested(row, "salesByAsin", "childAsin")
    if not asin:
        raise ValueError("Sales & Traffic row has no child ASIN")
    raw_date = row.get("date") or row.get("reportDate") or row.get("report_date")
    report_date = fallback_date if raw_date is None else dt.date.fromisoformat(str(raw_date)[:10])
    sales = row.get("salesByAsin") if isinstance(row.get("salesByAsin"), dict) else row
    traffic = row.get("trafficByAsin") if isinstance(row.get("trafficByAsin"), dict) else row
    record = {
        "child_asin": str(asin),
        "parent_asin": row.get("parentAsin") or row.get("parent_asin"),
        "sku": row.get("sku") or row.get("sellerSku"),
        "units_ordered": sales.get("unitsOrdered") or sales.get("units_ordered"),
        "ordered_product_sales": parse_money(sales.get("orderedProductSales") or sales.get("ordered_product_sales")),
        "total_order_items": sales.get("totalOrderItems") or sales.get("total_order_items"),
        "sessions": traffic.get("sessions"),
        "page_views": traffic.get("pageViews") or traffic.get("page_views"),
        "buy_box_percentage": traffic.get("buyBoxPercentage") or traffic.get("buy_box_percentage"),
        "unit_session_percentage": sales.get("unitSessionPercentage") or sales.get("unit_session_percentage"),
    }
    return report_date, str(asin), record


def load_sp_connection(conn, tenant_id: str) -> SpConnection:
    row = conn.execute(
        """
        select id, region, refresh_token_encrypted
          from amazon_connection
         where tenant_id = %s and provider = 'sp_api' and status = 'active'
         limit 1
        """,
        (tenant_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"tenant {tenant_id} has no active SP-API connection")
    if row["refresh_token_encrypted"] is None:
        raise RuntimeError(f"tenant {tenant_id} SP-API connection has no refresh token")
    client_id = os.environ.get("SPAPI_CLIENT_ID")
    client_secret = os.environ.get("SPAPI_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("SPAPI_CLIENT_ID and SPAPI_CLIENT_SECRET must be set")
    return SpConnection(str(row["id"]), row["region"], client_id, client_secret, unseal(bytes(row["refresh_token_encrypted"])))


def persist_rotated_refresh_token(conn, connection: SpConnection, client: SalesTrafficClient) -> None:
    credentials = getattr(client, "credentials", None)
    new_token = getattr(credentials, "refresh_token", None)
    if not new_token or new_token == connection.refresh_token:
        return
    sealed = seal(str(new_token))
    conn.execute(
        """
        update amazon_connection
           set refresh_token_encrypted = %s, key_version = %s, updated_at = now()
         where id = %s
        """,
        (sealed.ciphertext, sealed.key_version, connection.connection_id),
    )


def read_watermark(conn, tenant_id: str) -> dt.date | None:
    row = conn.execute("select last_complete_date from sync_watermark where tenant_id = %s and dataset = %s", (tenant_id, DATASET)).fetchone()
    return None if row is None else row["last_complete_date"]


def start_pipeline_run(conn, tenant_id: str, dates: list[dt.date]) -> uuid.UUID:
    row = conn.execute(
        "insert into pipeline_run (tenant_id, dataset, date_from, date_to, status) values (%s, %s, %s, %s, 'running') returning id",
        (tenant_id, DATASET, min(dates) if dates else None, max(dates) if dates else None),
    ).fetchone()
    return row["id"]


def upsert_raw_rows(conn, tenant_id: str, fallback_date: dt.date, rows: list[dict[str, Any]]) -> int:
    loaded = 0
    for row in rows:
        report_date, entity_id, record = normalize_row(row, fallback_date)
        conn.execute(
            """
            insert into raw.raw_sales_traffic_asin_daily (tenant_id, report_date, entity_id, record)
            values (%s, %s, %s, %s)
            on conflict (tenant_id, report_date, entity_id) do update set
                record = excluded.record,
                loaded_at = now()
            """,
            (tenant_id, report_date, entity_id, psycopg.types.json.Jsonb(record)),
        )
        loaded += 1
    return loaded


def finish_pipeline_run(conn, run_id: uuid.UUID, result: RunResult) -> None:
    status = "partial" if result.failed and result.succeeded else "failed" if result.failed else "success"
    conn.execute(
        """
        update pipeline_run set finished_at = now(), status = %s, rows_loaded = %s,
            error = %s, detail = %s where id = %s
        """,
        (status, result.rows_loaded, "\n".join(result.errors) or None, psycopg.types.json.Jsonb(result.__dict__), run_id),
    )


def update_watermark(conn, tenant_id: str, completed_dates: list[dt.date]) -> None:
    if not completed_dates:
        return
    conn.execute(
        """
        insert into sync_watermark (tenant_id, dataset, last_complete_date, last_attempt_at, last_status)
        values (%s, %s, %s, now(), 'success')
        on conflict (tenant_id, dataset) do update set
            last_complete_date = greatest(sync_watermark.last_complete_date, excluded.last_complete_date),
            last_attempt_at = excluded.last_attempt_at,
            last_status = excluded.last_status
        """,
        (tenant_id, DATASET, max(completed_dates)),
    )


def run_requests(conn, tenant_id: str, client: SalesTrafficClient, requests: Iterable[ReportRequest], *, dry_run: bool) -> RunResult:
    requests = list(requests)
    result = RunResult(tenant_id=tenant_id, dry_run=dry_run, requested=len(requests))
    if dry_run:
        result.succeeded = len(requests)
        return result
    for req in requests:
        try:
            report_id = client.create_report(SALES_AND_TRAFFIC, req.date, req.date, REPORT_OPTIONS)
            document_id = client.wait_for_report(report_id)
            rows = parse_report_payload(client.download_report(document_id))
            result.rows_loaded += upsert_raw_rows(conn, tenant_id, req.date, rows)
            result.report_ids.append(report_id)
            result.succeeded += 1
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{DATASET} {req.date}: {exc}")
    return result


def run(tenant_id: str, dry_run: bool = True, *, today: dt.date | None = None, client_factory: Callable[[SpConnection], SalesTrafficClient] | None = None) -> RunResult:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        dates = plan_dates(read_watermark(conn, tenant_id), today=today)
        run_id = start_pipeline_run(conn, tenant_id, dates)
        sp_connection = None if dry_run and client_factory is None else load_sp_connection(conn, tenant_id)
        client = (client_factory or _default_client)(sp_connection) if sp_connection else _DryClient()
        result = run_requests(conn, tenant_id, client, [ReportRequest(d) for d in dates], dry_run=dry_run)
        finish_pipeline_run(conn, run_id, result)
        if result.failed == 0:
            update_watermark(conn, tenant_id, dates)
        if sp_connection is not None:
            persist_rotated_refresh_token(conn, sp_connection, client)
        conn.commit()
        return result


def _default_client(connection: SpConnection) -> SpApiClient:
    return SpApiClient(SpApiCredentials(connection.client_id, connection.client_secret, connection.refresh_token), tenant_id=None, region=connection.region)


class _DryClient:
    def create_report(self, report_type, start, end, report_options=None):
        return f"dry-{report_type}-{start}"
    def wait_for_report(self, report_id: str, timeout_s: int = 3600) -> str:
        return f"document-{report_id}"
    def download_report(self, document_id: str) -> bytes:
        return b'{"salesAndTrafficByAsin": []}'


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SP-API Sales & Traffic ingestion")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--live", action="store_true", help="Call the configured SP-API endpoint")
    parser.add_argument("--sandbox", action="store_true", help="Call SP-API sandbox endpoint from SPAPI_ENDPOINT")
    parser.add_argument("--today", help="Override today's date as YYYY-MM-DD for smoke testing")
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    if args.live and args.sandbox:
        raise SystemExit("choose only one of --live or --sandbox")
    if args.sandbox:
        os.environ.setdefault("SPAPI_ENDPOINT", "https://sandbox.sellingpartnerapi-eu.amazon.com")
    today = dt.date.fromisoformat(args.today) if args.today else None
    result = run(args.tenant_id, dry_run=not (args.live or args.sandbox), today=today)
    mode = "sandbox" if args.sandbox else "live" if args.live else "dry-run"
    print(
        f"sales_traffic mode={mode} requested={result.requested} succeeded={result.succeeded} "
        f"failed={result.failed} rows_loaded={result.rows_loaded}"
    )
    for error in result.errors:
        print(f"ERROR {error}")


if __name__ == "__main__":
    main()
