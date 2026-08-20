"""First dlt pipeline: Sponsored Products daily reports.

Behaviour that matters:
  * first run backfills the FULL 95-day window, oldest day first
  * subsequent runs are incremental from the watermark
  * re-running a day upserts — it never duplicates
  * a missing day is recorded with a status, never silently skipped

Why oldest-first: the oldest day is the one about to fall out of Amazon's
retention window forever.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

BACKFILL_DAYS = 95
SETTLEMENT_LAG_DAYS = 3
REINGEST_DAYS = 14

DATASETS = {
    "ads_sp_campaign_daily": "spCampaigns",
    "ads_sp_ad_group_daily": "spAdGroups",
    "ads_sp_keyword_daily": "spTargeting",
    "ads_sp_search_term_daily": "spSearchTerm",
    "ads_sp_advertised_product_daily": "spAdvertisedProduct",
    "ads_sp_purchased_product_daily": "spPurchasedProduct",
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
    """Return the dates to fetch, oldest first.

    * no watermark  -> full backfill window
    * watermark set -> everything after it, plus a rolling re-ingest tail
                       because Amazon restates attributed sales
    """
    today = today or dt.date.today()
    newest = today - dt.timedelta(days=1)  # yesterday is the newest complete day
    oldest_available = today - dt.timedelta(days=backfill_days)

    if last_complete is None:
        start = oldest_available
    else:
        start = min(last_complete + dt.timedelta(days=1),
                    newest - dt.timedelta(days=reingest_days - 1))
        start = max(start, oldest_available)

    if start > newest:
        return []
    span = (newest - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(span)]


def find_gaps(expected: list[dt.date], present: set[dt.date]) -> list[dt.date]:
    """Missing days, oldest first — the ones closest to expiring."""
    return sorted(d for d in expected if d not in present)


def rules_safe_date(today: dt.date | None = None) -> dt.date:
    """Latest date the rules engine may act on (T-3 settlement lag)."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=SETTLEMENT_LAG_DAYS)


def run(tenant_id: str, dry_run: bool = True) -> None:
    """Wire up with dlt: resource per dataset, merge write disposition.

    Implementation checklist (M1-09):
      1. load credentials from the vault for this tenant
      2. read sync_watermark for each dataset
      3. plan_dates(...) -> chunk into report requests
      4. create/poll/download via AdsClient
      5. dlt merge on the natural key (tenant_id, report_date, entity_id)
      6. update sync_watermark + pipeline_run
    """
    raise NotImplementedError("see issue M1-09")
