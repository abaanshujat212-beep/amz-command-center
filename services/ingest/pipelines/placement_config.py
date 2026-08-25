"""Ingest current Ads campaign placement-bidding modifiers."""

from __future__ import annotations

import argparse
import os
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from services.actions.worker import load_ads_client, persist_rotated_refresh_token

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
PLACEMENTS = ("PLACEMENT_TOP", "PLACEMENT_PRODUCT_PAGE", "PLACEMENT_REST_OF_SEARCH")


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


def sync(client: CampaignClient, conn, tenant_id: str) -> int:
    loaded = 0
    next_token = None
    while True:
        payload = client.list_campaigns(next_token=next_token)
        rows = [row for campaign in _campaigns(payload) for row in extract_placement_rows(campaign)]
        loaded += upsert_rows(conn, tenant_id, rows)
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
