"""Selling Partner API client wrapper (EU endpoint, UK marketplace).

Wraps python-amazon-sp-api so pipelines depend on our interface, not the vendor's.

Every request is built from packages/shared/endpoints.py, so the copilot's answer
to "what can this system call?" is the same object the client calls (#33). A path
that is not catalogued cannot be requested — see tests/test_endpoint_discipline.py.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from packages.shared import endpoints as ep
from packages.shared.marketplaces import DEFAULT, Marketplace

# Kept as a re-export so existing imports keep working, but the catalog owns the
# number now. Two copies of a limit is how the Ads lookback drifted.
MAX_REPORT_HISTORY_DAYS = ep.SP_MAX_REPORT_HISTORY_DAYS


class ReportHistoryExceeded(ValueError):
    pass


class UnknownReportType(ValueError):
    """A report type not listed in the catalog.

    Raised before dispatch because sp.reports.create is rate limited to one
    request per 45 seconds: discovering a typo from Amazon's response is the
    slowest possible way to find it.
    """


class AttributionGranularityError(ValueError):
    """Sales & Traffic requested at a granularity that cannot be joined to Ads."""


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
        region: str = ep.DEFAULT_REGION,
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id
        self.region = region

    # ---------------------------------------------------------------- auth
    @property
    def token_url(self) -> str:
        """SP-API's LWA endpoint is global, unlike the Ads one."""
        return ep.SP_TOKEN_URL

    # ------------------------------------------------------- request seam
    def url(self, endpoint_key: str, **path_params: str) -> str:
        """The only way a URL is produced in this class."""
        return ep.url_for(endpoint_key, region=self.region, **path_params)

    def _call(self, endpoint_key: str, *, body: dict | None = None, **path_params: str):
        """Single dispatch point for every SP-API request.

        Rate limits here are published and brutally low (sp.reports.create is
        0.0222 rps — one request per 45 seconds), so the pacing logic belongs in
        one place and must read rate_limit_rps from the catalog rather than
        sleeping on a guessed constant.

        On 429, honour Retry-After. Never retry a report creation blindly: each
        retry consumes a scarce slot and may create a duplicate report.
        """
        endpoint = ep.endpoint(endpoint_key)  # raises if uncatalogued
        _ = self.url(endpoint_key, **path_params)
        _ = (endpoint.method, endpoint.rate_limit_rps, endpoint.burst)
        raise NotImplementedError("HTTP layer lands with M0-05")

    # ------------------------------------------------------------- reports
    @staticmethod
    def check_history(start: dt.date) -> None:
        oldest = dt.date.today() - dt.timedelta(days=MAX_REPORT_HISTORY_DAYS)
        if start < oldest:
            raise ReportHistoryExceeded(
                f"SP-API reports go back ~2 years (oldest: {oldest}, requested: {start})"
            )

    @staticmethod
    def check_report_type(report_type: str) -> None:
        if report_type not in ep.SP_REPORT_TYPES:
            raise UnknownReportType(
                f"'{report_type}' is not in SP_REPORT_TYPES. Add it to "
                f"packages/shared/endpoints.py with a note on its constraints — "
                f"known types: {sorted(ep.SP_REPORT_TYPES)}"
            )

    @staticmethod
    def check_attribution_granularity(report_type: str, report_options: dict | None) -> None:
        """Sales & Traffic is only useful at CHILD granularity.

        PARENT is accepted by Amazon and returns perfectly good-looking data. It
        just cannot be joined to the Ads advertisedAsin, so total sales end up
        attached to the wrong ASIN and TACoS becomes a confident wrong number.
        This is the exact failure mode this codebase keeps hitting, so it raises.
        """
        if report_type != SALES_AND_TRAFFIC:
            return
        options = report_options or {}
        granularity = options.get("asinGranularity")
        if granularity != "CHILD":
            raise AttributionGranularityError(
                f"{SALES_AND_TRAFFIC} requires asinGranularity='CHILD' "
                f"(got {granularity!r}). PARENT returns data that cannot be joined "
                "to the Ads advertisedAsin, which makes TACoS wrong without "
                "looking wrong."
            )
        if options.get("dateGranularity") != "DAY":
            raise AttributionGranularityError(
                f"{SALES_AND_TRAFFIC} requires dateGranularity='DAY' "
                f"(got {options.get('dateGranularity')!r}). Weekly or monthly rows "
                "cannot be aligned to daily ad spend."
            )

    def create_report(
        self,
        report_type: str,
        start: dt.date,
        end: dt.date,
        report_options: dict | None = None,
    ) -> str:
        """POST /reports/2021-06-30/reports. Returns a reportId, not data.

        For GET_SALES_AND_TRAFFIC_REPORT pass
        report_options={"dateGranularity": "DAY", "asinGranularity": "CHILD"} —
        enforced above rather than merely documented.

        Note the throttle: max 3 requests per 5 minutes for Sales & Traffic.
        """
        self.check_report_type(report_type)
        self.check_history(start)
        self.check_attribution_granularity(report_type, report_options)
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        body: dict = {
            "reportType": report_type,
            "marketplaceIds": [self.marketplace.marketplace_id],
            "dataStartTime": start.isoformat(),
            "dataEndTime": end.isoformat(),
        }
        if report_options:
            body["reportOptions"] = report_options
        return self._call("sp.reports.create", body=body)

    def wait_for_report(self, report_id: str, timeout_s: int = 3600) -> str:
        """Poll until DONE and return the reportDocumentId.

        FATAL and CANCELLED are terminal and must not be retried in a loop:
        a FATAL report usually means the request itself was wrong, so retrying
        burns the rate limit and reports success-shaped failure forever.
        """
        return self._call("sp.reports.get", reportId=report_id)

    def get_report_document(self, document_id: str) -> dict:
        """Resolve a document id to its short-lived download URL."""
        return self._call("sp.reports.document", reportDocumentId=document_id)

    def download_report(self, document_id: str) -> bytes:
        """Fetch and decompress (documents arrive gzipped).

        The URL from get_report_document expires quickly and must never be
        stored: a persisted link fails later in a way that looks like a data gap
        rather than an expired credential.
        """
        raise NotImplementedError("see M0-05")

    # ------------------------------------------------------------ catalog
    def get_inventory_summaries(self) -> dict:
        """FBA inventory — read before recommending any budget increase.

        Scaling spend on an out-of-stock ASIN is the most expensive avoidable
        mistake this system could make, and it looks like a healthy ACOS right up
        to the moment the listing goes dark.
        """
        return self._call("sp.inventory.summaries")


SALES_AND_TRAFFIC = "GET_SALES_AND_TRAFFIC_REPORT"
BRAND_ANALYTICS_SEARCH_TERMS = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"
BRAND_ANALYTICS_CATALOG_PERFORMANCE = (
    "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT"
)
