"""One-day UK SP-API smoke test; never commits sandbox observations or credentials."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from dataclasses import dataclass

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from packages.shared.marketplaces import UK
from services.ingest.clients.sp_api import SALES_AND_TRAFFIC, SpApiClient, SpApiCredentials
from services.ingest.pipelines.sales_traffic import (
    DATABASE_URL,
    REPORT_OPTIONS,
    SANDBOX_ENDPOINT,
    SalesTrafficClient,
    normalize_row,
    parse_report_payload,
    upsert_raw_rows,
)


class SandboxSmokeError(ValueError):
    """A safe diagnostic that includes no response bodies, endpoints or identifiers."""


@dataclass(frozen=True)
class SandboxEvidence:
    date: dt.date
    row_count: int


def _database_identity(dsn: str) -> tuple:
    try:
        settings = conninfo_to_dict(dsn)
    except psycopg.Error as exc:
        raise SandboxSmokeError("invalid sandbox database configuration") from exc
    if settings.get("service"):
        raise SandboxSmokeError("sandbox verification requires an explicit local database")
    return (
        settings.get("hostaddr", settings.get("host", "")),
        settings.get("port", "5432"),
        settings.get("dbname") or settings.get("user", ""),
    )


def _sandbox_dsn() -> str:
    dsn = os.environ.get("SPAPI_SANDBOX_DATABASE_URL", "").strip()
    if not dsn:
        raise SandboxSmokeError("SPAPI_SANDBOX_DATABASE_URL is required; use a disposable local database")
    host, _, database = _database_identity(dsn)
    if host not in ("127.0.0.1", "localhost", "::1") or not database:
        raise SandboxSmokeError("sandbox verification requires a named loopback database")
    # A different database name also prevents common host alias mixups.
    if database == _database_identity(os.environ.get("DATABASE_URL") or DATABASE_URL)[2]:
        raise SandboxSmokeError("the sandbox database must have a different name from DATABASE_URL")
    return dsn


def _sandbox_client() -> SpApiClient:
    if (os.environ.get("SPAPI_ENDPOINT") or SANDBOX_ENDPOINT).rstrip("/") != SANDBOX_ENDPOINT:
        raise SandboxSmokeError("SPAPI_ENDPOINT conflicts with the official EU sandbox host")
    names = ("SPAPI_SANDBOX_CLIENT_ID", "SPAPI_SANDBOX_CLIENT_SECRET", "SPAPI_SANDBOX_REFRESH_TOKEN")
    values = [os.environ.get(name, "").strip() for name in names]
    if not all(values):
        raise SandboxSmokeError("missing one or more dedicated SPAPI_SANDBOX credentials")
    return SpApiClient(SpApiCredentials(*values), marketplace=UK, region="eu", base_url=SANDBOX_ENDPOINT)


def smoke(conn, tenant_id: str, day: dt.date, client: SalesTrafficClient) -> SandboxEvidence:
    """Exercise report creation, parsing and raw replay in one rollback-only transaction."""
    stage = "tenant scope"
    try:
        with conn.transaction(force_rollback=True):
            conn.execute("select set_tenant(%s)", (tenant_id,))
            stage = "create report"
            report_id = client.create_report(SALES_AND_TRAFFIC, day, day, REPORT_OPTIONS)
            stage = "poll report"
            document_id = client.wait_for_report(report_id, timeout_s=120)
            stage = "download report"
            payload = client.download_report(document_id)
            stage = "validate Sales & Traffic rows"
            rows = parse_report_payload(payload)
            if not rows:
                raise SandboxSmokeError("sandbox returned no Sales & Traffic ASIN rows; raw-load proof unavailable")
            asins: set[str] = set()
            for row in rows:
                report_day, asin, _ = normalize_row(row, day)
                if report_day != day or asin in asins:
                    raise SandboxSmokeError("sandbox rows do not match unique requested CHILD ASIN/day grain")
                asins.add(asin)

            stage = "verify rollback-only raw replay"
            for _ in range(2):
                upsert_raw_rows(conn, tenant_id, day, rows)
                count = conn.execute(
                    """
                    select count(*) as observed from raw.raw_sales_traffic_asin_daily
                    where tenant_id = %s and report_date = %s and entity_id = any(%s::text[])
                    """,
                    (tenant_id, day, sorted(asins)),
                ).fetchone()["observed"]
                if count != len(asins):
                    raise SandboxSmokeError("sandbox raw row count did not match after upsert")
    except SandboxSmokeError:
        raise
    except httpx.HTTPStatusError as exc:
        raise SandboxSmokeError(f"{stage}: HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        raise SandboxSmokeError(f"{stage}: {type(exc).__name__}") from exc
    return SandboxEvidence(day, len(asins))


def cli_smoke(tenant_id: str, day: dt.date) -> None:
    try:
        uuid.UUID(tenant_id)
    except ValueError as exc:
        raise SystemExit("sandbox tenant must be an existing UUID in the disposable database") from exc
    try:
        dsn = _sandbox_dsn()
        client = _sandbox_client()
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            evidence = smoke(conn, tenant_id, day, client)
    except SandboxSmokeError as exc:
        raise SystemExit(f"sales_traffic mode=sandbox failed: {exc}") from None
    except psycopg.Error as exc:
        raise SystemExit(f"sales_traffic mode=sandbox database connection failed: {type(exc).__name__}") from None
    print(f"sales_traffic mode=sandbox market=GB date={evidence.date} rows={evidence.row_count} replay=verified rollback=yes")
