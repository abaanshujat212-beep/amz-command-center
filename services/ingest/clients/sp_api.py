"""Selling Partner API client wrapper (EU endpoint, UK marketplace).

Wraps python-amazon-sp-api so pipelines depend on our interface, not the vendor's.
SP-API reports accept dataStartTime up to about two years back; anything older is
rejected before a request is made.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from packages.shared.marketplaces import DEFAULT, Marketplace

MAX_REPORT_HISTORY_DAYS = 730


class ReportHistoryExceeded(ValueError):
    pass


@dataclass
class SpApiCredentials:
    client_id: str
    client_secret: str
    refresh_token: str


class SpApiClient:
    def __init__(
        self,
        credentials: SpApiCredentials,
        marketplace: Marketplace = DEFAULT,
        tenant_id: str | None = None,
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id

    @staticmethod
    def check_history(start: dt.date) -> None:
        oldest = dt.date.today() - dt.timedelta(days=MAX_REPORT_HISTORY_DAYS)
        if start < oldest:
            raise ReportHistoryExceeded(
                f"SP-API reports go back ~2 years (oldest: {oldest}, requested: {start})"
            )

    def create_report(
        self,
        report_type: str,
        start: dt.date,
        end: dt.date,
        report_options: dict | None = None,
    ) -> str:
        """POST /reports/2021-06-30/reports.

        For GET_SALES_AND_TRAFFIC_REPORT always pass
        report_options={"dateGranularity": "DAY", "asinGranularity": "CHILD"} —
        CHILD is what joins to the Ads advertisedAsin. PARENT silently breaks
        attribution and makes TACoS fiction.
        """
        self.check_history(start)
        raise NotImplementedError("implement with python-amazon-sp-api (see M0-05)")

    def wait_for_report(self, report_id: str, timeout_s: int = 3600) -> str:
        raise NotImplementedError("see M0-05")

    def download_report(self, document_id: str) -> bytes:
        """Fetch and decompress (documents arrive gzipped)."""
        raise NotImplementedError("see M0-05")


SALES_AND_TRAFFIC = "GET_SALES_AND_TRAFFIC_REPORT"
BRAND_ANALYTICS_SEARCH_TERMS = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"
BRAND_ANALYTICS_CATALOG_PERFORMANCE = (
    "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT"
)
