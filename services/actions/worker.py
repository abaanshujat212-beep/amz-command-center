"""Approved-action worker seam.

Loads approved actions, re-reads the live Amazon baseline through an injected
client, applies the write, and records the state-machine result. The default
client is intentionally dry-run until the Ads HTTP layer is implemented.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from services.actions import state_machine as sm

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


class ActionClient(Protocol):
    def read_before_value(self, action: sm.Action) -> dict | None: ...
    def apply(self, action: sm.Action) -> dict: ...
    def rollback(self, action: sm.Action) -> dict: ...


@dataclass
class WorkerResult:
    scanned: int = 0
    applied: int = 0
    failed: int = 0
    rolled_back: int = 0


class DryRunActionClient:
    def read_before_value(self, action: sm.Action) -> dict | None:
        return action.before_value

    def apply(self, action: sm.Action) -> dict:
        return {"status": "WOULD_DO", "action_id": action.id}

    def rollback(self, action: sm.Action) -> dict:
        return {"status": "WOULD_ROLLBACK", "action_id": action.id}


def _to_action(row: dict) -> sm.Action:
    return sm.Action(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        action_type=row["action_type"],
        before_value=row["before_value"],
        after_value=row["after_value"],
        status=sm.Status(row["status"]),
        approved_by=str(row["approved_by"]) if row["approved_by"] else None,
        approved_at=row["approved_at"],
        applied_at=row["applied_at"],
    )


def fetch_approved(conn, tenant_id: str, limit: int) -> list[sm.Action]:
    rows = conn.execute(
        """
        select id, tenant_id, entity_type, entity_id, action_type, before_value,
               after_value, status, approved_by, approved_at, applied_at
          from action
         where tenant_id = %s and status = 'approved'
         order by approved_at nulls first, requested_at
         limit %s
        """,
        (tenant_id, limit),
    ).fetchall()
    return [_to_action(r) for r in rows]


def persist_apply_result(conn, action: sm.Action, api_response: dict | None = None) -> None:
    conn.execute(
        """
        update action
           set status = %s, before_value = %s, applied_at = %s,
               error = %s, api_response = %s
         where tenant_id = %s and id = %s
        """,
        (
            action.status.value,
            psycopg.types.json.Jsonb(action.before_value),
            action.applied_at,
            action.error,
            psycopg.types.json.Jsonb(api_response or {}),
            action.tenant_id,
            action.id,
        ),
    )


def apply_action(action: sm.Action, client: ActionClient, *, now: dt.datetime) -> tuple[sm.Action, dict | None]:
    live_before = client.read_before_value(action)
    try:
        response = client.apply(action)
    except Exception as exc:
        return sm.apply(action, now=now, live_before_value=live_before, api_ok=False, error=str(exc)), None
    return sm.apply(action, now=now, live_before_value=live_before, api_ok=True), response


def run_once(tenant_id: str, *, limit: int = 25, client: ActionClient | None = None, database_url: str = DATABASE_URL) -> WorkerResult:
    result = WorkerResult()
    client = client or DryRunActionClient()
    now = dt.datetime.now(dt.timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        actions = fetch_approved(conn, tenant_id, limit)
        result.scanned = len(actions)
        for action in actions:
            updated, response = apply_action(action, client, now=now)
            persist_apply_result(conn, updated, response)
            if updated.status == sm.Status.APPLIED:
                result.applied += 1
            else:
                result.failed += 1
        conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved actions for one tenant")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    result = run_once(args.tenant_id, limit=args.limit)
    print(f"actions scanned={result.scanned} applied={result.applied} failed={result.failed}")


if __name__ == "__main__":
    main()
