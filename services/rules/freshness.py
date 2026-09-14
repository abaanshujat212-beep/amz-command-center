"""Tenant-scoped source freshness resolved only from persisted evidence."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from enum import StrEnum

SCOPE_DATASETS: dict[str, tuple[str, ...]] = {
    "campaign": ("ads_sp_campaign_daily",),
    "keyword": ("ads_sp_keyword_daily",),
    "search_term": ("ads_sp_search_term_daily",),
    "placement": ("ads_sp_placement_daily",),
}


class FreshnessState(StrEnum):
    FRESH = "fresh"
    MISSING = "source_missing"
    FAILED = "source_failed"
    PARTIAL = "source_partial"
    STALE = "source_stale"
    UNSETTLED = "source_unsettled"


@dataclass(frozen=True)
class SourceFreshness:
    state: FreshnessState
    datasets: tuple[str, ...]
    data_through: dt.date | None = None
    data_loaded_at: dt.datetime | None = None
    detail: str | None = None

    @property
    def usable(self) -> bool:
        return self.state is FreshnessState.FRESH

    @property
    def block_reason(self) -> str:
        return self.state.value

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_source_freshness(
    cur,
    *,
    tenant_id: str,
    scope: str,
    now: dt.datetime,
    settled_cutoff: dt.date,
    max_age_hours: int,
) -> SourceFreshness:
    """Resolve the weakest required dataset; never substitute process time."""
    datasets = SCOPE_DATASETS.get(scope)
    if not datasets:
        return SourceFreshness(FreshnessState.MISSING, (), detail=f"no datasets mapped for {scope}")
    cur.execute(
        """
        select required.dataset, w.last_complete_date, w.last_attempt_at, w.last_status,
               latest.status as run_status, latest.finished_at, latest.date_to
          from unnest(%s::text[]) as required(dataset)
          left join sync_watermark w
            on w.tenant_id = %s and w.dataset = required.dataset
          left join lateral (
            select status, finished_at, date_to
              from pipeline_run
             where tenant_id = %s and dataset = required.dataset
             order by started_at desc
             limit 1
          ) latest on true
        """,
        (list(datasets), tenant_id, tenant_id),
    )
    rows = cur.fetchall()
    if len(rows) != len(datasets):
        return SourceFreshness(FreshnessState.MISSING, datasets, detail="required evidence absent")
    for row in rows:
        if row["last_complete_date"] is None or row["finished_at"] is None:
            return SourceFreshness(
                FreshnessState.MISSING, datasets, detail=f"{row['dataset']}: watermark or run missing"
            )
        if row["last_status"] == "partial" or row["run_status"] == "partial":
            return SourceFreshness(
                FreshnessState.PARTIAL, datasets, detail=f"{row['dataset']}: partial load"
            )
        if row["last_status"] != "success" or row["run_status"] != "success":
            return SourceFreshness(
                FreshnessState.FAILED,
                datasets,
                detail=f"{row['dataset']}: watermark={row['last_status']} run={row['run_status']}",
            )
    loaded_at = min(row["finished_at"] for row in rows)
    data_through = min(min(row["last_complete_date"] for row in rows), settled_cutoff)
    if data_through > settled_cutoff:
        return SourceFreshness(FreshnessState.UNSETTLED, datasets, detail="no settled cutoff")
    age_hours = (now - loaded_at).total_seconds() / 3600
    if age_hours > max_age_hours:
        return SourceFreshness(
            FreshnessState.STALE,
            datasets,
            data_through=data_through,
            data_loaded_at=loaded_at,
            detail=f"oldest required load is {age_hours:.0f}h old",
        )
    return SourceFreshness(
        FreshnessState.FRESH,
        datasets,
        data_through=data_through,
        data_loaded_at=loaded_at,
    )
