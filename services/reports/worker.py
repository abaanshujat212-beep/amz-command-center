"""Execute governed report jobs from allowlisted dbt mart contracts."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from services.reports.artifacts import render_claimed_job
from services.reports.jobs import claim_next_job, fail_job
from services.reports.storage import LocalPrivateArtifactStore

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


@dataclass(frozen=True)
class SourceContract:
    columns: tuple[str, ...]
    allowed_filters: frozenset[str]


CAMPAIGN_COLUMNS = (
    "report_date",
    "campaign_id",
    "campaign_name",
    "campaign_status",
    "targeting_type",
    "impressions",
    "clicks",
    "cost",
    "attributed_orders_7d",
    "attributed_sales_7d",
    "acos",
    "roas",
    "ctr",
    "cvr",
    "cpc",
    "tacos",
    "break_even_acos",
    "economics_incomplete",
    "is_settled",
)
SOURCE_CONTRACTS = {
    "mart-ppc-campaign-daily-v1": SourceContract(
        CAMPAIGN_COLUMNS, frozenset({"campaign_status", "targeting_type"})
    )
}


def _source_query(snapshot: dict[str, Any], filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Build SQL only from a static source registry and validated scalar filters."""
    name = snapshot.get("source_contract")
    contract = SOURCE_CONTRACTS.get(name)
    if contract is None:
        raise ValueError(f"unsupported report source contract: {name}")
    unexpected = set(filters) - contract.allowed_filters
    if unexpected:
        raise ValueError(f"unsupported report filters: {sorted(unexpected)}")
    definition = snapshot.get("definition") or {}
    if tuple(definition.get("columns") or ()) != contract.columns:
        raise ValueError("report definition columns do not match the registered source contract")
    clauses = ["report_date between %s and %s"]
    params: list[Any] = []
    for key in ("campaign_status", "targeting_type"):
        value = filters.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError(f"{key} filter must be a short string")
        clauses.append(f"{key} = %s")
        params.append(value)
    columns = ",".join(contract.columns)
    sql = (
        f"select {columns} from mart_ppc_campaign_daily "
        f"where {' and '.join(clauses)} order by report_date,campaign_id"
    )
    return sql, params


def run_once(
    tenant_id: str,
    *,
    worker_id: str,
    artifact_root: str,
    database_url: str = DATABASE_URL,
) -> str | None:
    """Claim and render one job; claim and terminal outcome remain observable."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        claimed = claim_next_job(conn, tenant_id=tenant_id, worker_id=worker_id)
        conn.commit()
        if claimed is None:
            return None
        job_id = claimed.id
        try:
            conn.execute("select set_tenant(%s)", (tenant_id,))
            job = conn.execute(
                """select definition_snapshot,date_from,date_to,filters
                     from report_job where tenant_id=%s and id=%s and status='running'
                     for update""",
                (tenant_id, job_id),
            ).fetchone()
            if job is None:
                raise LookupError("claimed report job disappeared")
            sql, filter_params = _source_query(job["definition_snapshot"], job["filters"])
            params = [job["date_from"], job["date_to"], *filter_params]
            rows = conn.execute(sql, params).fetchall()
            conn.execute(
                """update report_job set progress_current=%s,progress_total=%s,heartbeat_at=now()
                    where tenant_id=%s and id=%s and status='running' and worker_id=%s""",
                (len(rows), len(rows), tenant_id, job_id, worker_id),
            )
            contract = SOURCE_CONTRACTS[job["definition_snapshot"]["source_contract"]]
            retention = conn.execute(
                "select least(greatest(retention_days,1),3650) days from tenant where id=%s",
                (tenant_id,),
            ).fetchone()["days"]
            render_claimed_job(
                conn,
                tenant_id=tenant_id,
                job_id=job_id,
                worker_id=worker_id,
                columns=contract.columns,
                rows=rows,
                store=LocalPrivateArtifactStore(artifact_root),
                retention_days=int(retention),
            )
            conn.commit()
            return job_id
        except Exception as exc:
            conn.rollback()
            conn.execute("select set_tenant(%s)", (tenant_id,))
            fail_job(
                conn,
                tenant_id=tenant_id,
                job_id=job_id,
                worker_id=worker_id,
                error=str(exc)[:2000] or type(exc).__name__,
            )
            conn.commit()
            return job_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one governed report job")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--worker-id", default="report-worker")
    parser.add_argument("--artifact-root", default=os.environ.get("REPORT_ARTIFACT_ROOT"))
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    if not args.artifact_root:
        raise SystemExit("--artifact-root or REPORT_ARTIFACT_ROOT is required")
    job_id = run_once(args.tenant_id, worker_id=args.worker_id, artifact_root=args.artifact_root)
    print(f"report_job={job_id or 'none'}")


if __name__ == "__main__":
    main()
