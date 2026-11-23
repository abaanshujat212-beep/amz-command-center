"""Ingest current Ads campaign placement-bidding modifiers."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from services.actions.worker import load_ads_client, persist_rotated_refresh_token

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
PLACEMENTS = ("PLACEMENT_TOP", "PLACEMENT_PRODUCT_PAGE", "PLACEMENT_REST_OF_SEARCH")
API_VERSION = "sp-campaigns-v3"
STRATEGIES = {
    "manual": "fixed",
    "fixed": "fixed",
    "legacyforsales": "dynamic_down_only",
    "dynamic_down_only": "dynamic_down_only",
    "autoforsales": "dynamic_up_down",
    "dynamic_up_down": "dynamic_up_down",
}


class CampaignClient(Protocol):
    def list_campaigns(self, next_token: str | None = None, campaign_ids: list[str] | None = None) -> dict: ...


def _campaigns(payload: dict) -> list[dict]:
    return list(payload.get("campaigns") or payload.get("campaignResponse") or [])


def extract_placement_rows(campaign: dict) -> list[dict]:
    campaign_id = str(campaign.get("campaignId") or campaign.get("campaign_id") or "")
    if not campaign_id:
        return []
    configured = {
        str(row.get("placement")): row.get("percentage", 0)
        for row in (campaign.get("dynamicBidding") or {}).get("placementBidding") or []
    }
    return [
        {"campaign_id": campaign_id, "placement": placement, "percentage": configured.get(placement, 0), "record": campaign}
        for placement in PLACEMENTS
    ]


def extract_native_control_row(campaign: dict, *, observed_at: dt.datetime) -> dict | None:
    campaign_id = str(campaign.get("campaignId") or campaign.get("campaign_id") or "")
    if not campaign_id:
        return None
    dynamic = campaign.get("dynamicBidding") or {}
    raw_strategy = str(dynamic.get("strategy") or campaign.get("biddingStrategy") or "unknown")
    strategy_key = raw_strategy.replace("-", "_").replace(" ", "_").lower()
    strategy = STRATEGIES.get(strategy_key.replace("_", ""), STRATEGIES.get(strategy_key, raw_strategy or "unknown"))
    source_time = campaign.get("lastUpdatedDateTime") or campaign.get("lastUpdatedDate")
    if source_time:
        parsed = dt.datetime.fromisoformat(str(source_time).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
    else:
        parsed = observed_at
    return {
        "campaign_id": campaign_id,
        "bidding_strategy": strategy,
        "bidding_strategy_supported": strategy in set(STRATEGIES.values()),
        "budget_rule_active": bool(campaign.get("budgetRuleActive") or campaign.get("budgetRules")),
        "schedule_rule_active": bool(campaign.get("scheduleRuleActive") or campaign.get("scheduleRules")),
        "rule_based_bidding_active": bool(campaign.get("biddingRuleActive") or campaign.get("biddingRules")),
        "cost_control_active": bool(campaign.get("costControl") or dynamic.get("costControl")),
        "source_observed_at": parsed,
        "source_api_version": API_VERSION,
        "source_fingerprint": hashlib.sha256(json.dumps(campaign, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
        "source_record": campaign,
    }


def upsert_rows(conn, tenant_id: str, rows: list[dict]) -> int:
    loaded = 0
    for row in rows:
        conn.execute(
            """
            insert into raw.raw_ads_placement_config (tenant_id, campaign_id, placement, percentage, record)
            values (%s, %s, %s, %s, %s)
            """,
            (tenant_id, row["campaign_id"], row["placement"], row["percentage"], psycopg.types.json.Jsonb(row["record"])),
        )
        loaded += 1
    return loaded


def insert_native_control_rows(conn, tenant_id: str, rows: list[dict]) -> int:
    loaded = 0
    for row in rows:
        result = conn.execute(
            """
            insert into campaign_native_control_state (
              tenant_id, campaign_id, bidding_strategy, bidding_strategy_supported,
              budget_rule_active, schedule_rule_active, rule_based_bidding_active,
              cost_control_active, source_observed_at, source_api_version,
              source_fingerprint, source_record
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (tenant_id, campaign_id, source_api_version, source_fingerprint) do nothing
            returning id
            """,
            (tenant_id, row["campaign_id"], row["bidding_strategy"], row["bidding_strategy_supported"], row["budget_rule_active"], row["schedule_rule_active"], row["rule_based_bidding_active"], row["cost_control_active"], row["source_observed_at"], row["source_api_version"], row["source_fingerprint"], psycopg.types.json.Jsonb(row["source_record"])),
        )
        if result.fetchone() is not None:
            loaded += 1
    return loaded


def sync(client: CampaignClient, conn, tenant_id: str) -> int:
    loaded = 0
    next_token = None
    while True:
        payload = client.list_campaigns(next_token=next_token)
        campaigns = _campaigns(payload)
        observed_at = dt.datetime.now(dt.timezone.utc)
        rows = [row for campaign in campaigns for row in extract_placement_rows(campaign)]
        loaded += upsert_rows(conn, tenant_id, rows)
        native_rows = [row for campaign in campaigns if (row := extract_native_control_row(campaign, observed_at=observed_at)) is not None]
        insert_native_control_rows(conn, tenant_id, native_rows)
        next_token = payload.get("nextToken") or payload.get("next_token")
        if not next_token:
            return loaded


def run(tenant_id: str, *, database_url: str = DATABASE_URL, client: CampaignClient | None = None) -> int:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        ads_client = None
        if client is None:
            ads_client = load_ads_client(conn, tenant_id)
            client = ads_client
        loaded = sync(client, conn, tenant_id)
        if ads_client is not None:
            persist_rotated_refresh_token(conn, ads_client)
        conn.commit()
        return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Ads campaign placement modifiers")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    print(f"placement config rows loaded={run(args.tenant_id)}")


if __name__ == "__main__":
    main()
