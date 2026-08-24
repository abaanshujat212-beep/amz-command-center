"""Command runner for rules evaluation.

The engine already knows how to evaluate one tenant inside an existing database
connection. This module adds the operational seam: resolve the tenant, run the
engine, and print a compact summary suitable for cron/worker logs.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict

import psycopg

from services.rules.engine import RunSummary, evaluate_tenant

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


def run_once(tenant_id: str, *, database_url: str = DATABASE_URL) -> RunSummary:
    with psycopg.connect(database_url) as conn:
        return evaluate_tenant(conn, tenant_id)


def summary_line(summary: RunSummary) -> str:
    return (
        f"rules_evaluate tenant={summary.tenant_id} run={summary.run_id} "
        f"rules={summary.rules_run} entities={summary.entities_evaluated} "
        f"matched={summary.matched} proposed={summary.proposed} "
        f"flagged={summary.flagged} errors={len(summary.errors)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate enabled rules for one tenant")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--json", action="store_true", help="Print the full RunSummary dict")
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    summary = run_once(args.tenant_id)
    if args.json:
        print(asdict(summary))
    else:
        print(summary_line(summary))
        for error in summary.errors:
            print(f"ERROR {error}")


if __name__ == "__main__":
    main()
