"""First dlt pipeline: Sponsored Products daily reports."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

BACKFILL_DAYS = 95
SETTLEMENT_LAG_DAYS = 3
REINGEST_DAYS = 14


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


def run(tenant_id: str, dry_run: bool = True) -> None:
    raise NotImplementedError("see issue M1-09")
