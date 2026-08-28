"""Approved-action worker with Ads-client wiring and refresh-token persistence."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from services.actions import state_machine as sm
from services.ingest.clients.ads_api import AdsClient, AdsCredentials
from services.ingest.security.vault import seal, unseal

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
    alerts_created: int = 0


class DryRunActionClient:
    def read_before_value(self, action: sm.Action) -> dict | None:
        return action.before_value

    def apply(self, action: sm.Action) -> dict:
        return {"status": "WOULD_DO", "action_id": action.id}

    def rollback(self, action: sm.Action) -> dict:
        return {"status": "WOULD_ROLLBACK", "action_id": action.id}


class AdsActionClient:
    """Translate approved action rows into Ads API reads and mutations."""

    def __init__(self, ads: AdsClient) -> None:
        self.ads = ads

    def read_before_value(self, action: sm.Action) -> dict | None:
        if action.action_type == "set_bid" and action.entity_type in {"keyword", "target"}:
            return self.ads.keyword_bid(action.entity_id)
        if action.action_type == "set_placement_modifier":
            placement = str(action.after_value["placement"])
            return self.ads.placement_modifier(action.entity_id, placement)
        return action.before_value

    def apply(self, action: sm.Action) -> dict:
        value = action.after_value.get("value")
        if action.action_type == "set_bid" and action.entity_type in {"keyword", "target"}:
            return self.ads.update_bid(action.entity_id, float(value), dry_run=False)
        if action.action_type == "set_placement_modifier":
            return self.ads.update_placement_modifier(
                action.entity_id,
                str(action.after_value["placement"]),
                float(value),
                float(action.before_value["value"]) if action.before_value else None,
                dry_run=False,
            )
        raise NotImplementedError(f"Ads action not wired yet: {action.entity_type}/{action.action_type}")

    def rollback(self, action: sm.Action) -> dict:
        if action.before_value is None:
            raise RuntimeError("cannot rollback without before_value")
        original = action.before_value.get("value")
        if action.action_type == "set_bid" and action.entity_type in {"keyword", "target"}:
            return self.ads.update_bid(action.entity_id, float(original), dry_run=False)
        raise NotImplementedError(f"Ads rollback not wired yet: {action.entity_type}/{action.action_type}")


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


def load_ads_client(conn, tenant_id: str) -> AdsClient:
    row = conn.execute(
        """
        select c.id, c.region, c.refresh_token_encrypted, p.profile_id
          from amazon_connection c
          left join ads_profile p on p.connection_id = c.id and p.tenant_id = c.tenant_id
         where c.tenant_id = %s and c.provider = 'ads_api' and c.status = 'active'
         order by p.created_at nulls last
         limit 1
        """,
        (tenant_id,),
    ).fetchone()
    if row is None or row["refresh_token_encrypted"] is None:
        raise RuntimeError(f"tenant {tenant_id} has no active Ads API refresh token")
    client_id = os.environ.get("ADS_CLIENT_ID")
    client_secret = os.environ.get("ADS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("ADS_CLIENT_ID and ADS_CLIENT_SECRET must be set")
    ads = AdsClient(
        AdsCredentials(client_id, client_secret, unseal(bytes(row["refresh_token_encrypted"])), row["profile_id"]),
        tenant_id=tenant_id,
        region=row["region"],
    )
    ads.connection_id = row["id"]
    return ads


def persist_rotated_refresh_token(conn, ads: AdsClient) -> None:
    connection_id = getattr(ads, "connection_id", None)
    if connection_id is None:
        return
    sealed = seal(ads.credentials.refresh_token)
    conn.execute(
        """
        update amazon_connection
           set refresh_token_encrypted = %s, key_version = %s, updated_at = now()
         where id = %s
        """,
        (sealed.ciphertext, sealed.key_version, connection_id),
    )


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


def persist_worker_alert(
    conn,
    tenant_id: str,
    *,
    kind: str,
    severity: str,
    title: str,
    entity_ref: str,
    detail: dict,
) -> bool:
    existing = conn.execute(
        """
        select id from alert
         where tenant_id = %s and kind = %s and entity_ref = %s and resolved_at is null
         limit 1
        """,
        (tenant_id, kind, entity_ref),
    ).fetchone()
    if existing is not None:
        return False
    conn.execute(
        """
        insert into alert (tenant_id, kind, severity, title, detail, entity_ref)
        values (%s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, kind, severity, title, psycopg.types.json.Jsonb(detail), entity_ref),
    )
    return True


def persist_action_failure_alert(conn, action: sm.Action) -> bool:
    """Create one open alert per failed action so dashboard operators see it."""
    if action.status != sm.Status.FAILED:
        return False
    return persist_worker_alert(
        conn,
        action.tenant_id,
        kind="action_failed",
        severity="critical",
        title=f"Action {action.id} failed: {action.action_type}",
        entity_ref=action.id,
        detail={
            "action_id": action.id,
            "entity_type": action.entity_type,
            "entity_id": action.entity_id,
            "action_type": action.action_type,
            "error": action.error,
        },
    )


def persist_auth_failure_alert(conn, tenant_id: str, error: str) -> bool:
    return persist_worker_alert(
        conn,
        tenant_id,
        kind="auth_expired",
        severity="critical",
        title="Ads action worker could not load credentials",
        entity_ref="ads_api",
        detail={"provider": "ads_api", "error": error},
    )


def apply_action(action: sm.Action, client: ActionClient, *, now: dt.datetime) -> tuple[sm.Action, dict | None]:
    live_before = client.read_before_value(action)
    try:
        response = client.apply(action)
    except Exception as exc:
        return sm.apply(action, now=now, live_before_value=live_before, api_ok=False, error=str(exc)), None
    return sm.apply(action, now=now, live_before_value=live_before, api_ok=True), response


def run_once(
    tenant_id: str,
    *,
    limit: int = 25,
    client: ActionClient | None = None,
    database_url: str = DATABASE_URL,
    live_ads: bool = False,
) -> WorkerResult:
    result = WorkerResult()
    now = dt.datetime.now(dt.timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        ads_client = None
        if client is None:
            if live_ads:
                try:
                    ads_client = load_ads_client(conn, tenant_id)
                except RuntimeError as exc:
                    if persist_auth_failure_alert(conn, tenant_id, str(exc)):
                        result.alerts_created += 1
                    conn.commit()
                    return result
                client = AdsActionClient(ads_client)
            else:
                client = DryRunActionClient()
        actions = fetch_approved(conn, tenant_id, limit)
        result.scanned = len(actions)
        for action in actions:
            updated, response = apply_action(action, client, now=now)
            persist_apply_result(conn, updated, response)
            if updated.status == sm.Status.APPLIED:
                result.applied += 1
            else:
                result.failed += 1
                if persist_action_failure_alert(conn, updated):
                    result.alerts_created += 1
        if ads_client is not None:
            persist_rotated_refresh_token(conn, ads_client)
        conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved actions for one tenant")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--live-ads", action="store_true", help="Use the real Ads client instead of dry-run")
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    result = run_once(args.tenant_id, limit=args.limit, live_ads=args.live_ads)
    print(
        f"actions scanned={result.scanned} applied={result.applied} "
        f"failed={result.failed} alerts_created={result.alerts_created}"
    )


if __name__ == "__main__":
    main()
