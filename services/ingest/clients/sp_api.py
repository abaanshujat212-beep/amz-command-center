"""Selling Partner API client wrapper (EU endpoint, UK marketplace)."""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from packages.shared import endpoints as ep
from packages.shared.marketplaces import DEFAULT, Marketplace
from services.ingest.clients import rate_limit

MAX_REPORT_HISTORY_DAYS = ep.SP_MAX_REPORT_HISTORY_DAYS


class ReportHistoryExceeded(ValueError):
    pass


class UnknownReportType(ValueError):
    pass


class AttributionGranularityError(ValueError):
    pass


class SpApiAuthError(RuntimeError):
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
        region: str = ep.DEFAULT_REGION,
        timeout_s: float = 60.0,
        base_url: str | None = None,
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id
        self.region = region
        self.timeout_s = timeout_s
        endpoint_override = base_url or os.environ.get("SPAPI_ENDPOINT") or ""
        self.base_url = endpoint_override.rstrip(chr(47)) or None
        self._access_token: str | None = None
        self._access_expires_at: dt.datetime | None = None

    @property
    def token_url(self) -> str:
        return ep.SP_TOKEN_URL

    def _refresh_access_token(self) -> str:
        response = httpx.post(
            self.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.credentials.refresh_token,
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
            },
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise SpApiAuthError(f"SP-API token refresh failed: HTTP {response.status_code}")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise SpApiAuthError("SP-API token refresh response did not include access_token")
        expires_in = int(payload.get("expires_in", 3600))
        self._access_token = str(token)
        self._access_expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(expires_in - 60, 60))
        new_refresh = payload.get("refresh_token")
        if new_refresh:
            self.credentials.refresh_token = str(new_refresh)
        return self._access_token

    @property
    def access_token(self) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        if self._access_token and self._access_expires_at and now < self._access_expires_at:
            return self._access_token
        return self._refresh_access_token()

    def headers(self) -> dict[str, str]:
        return {
            "x-amz-access-token": self.access_token,
            "Content-Type": "application/json",
        }

    def url(self, endpoint_key: str, **path_params: str) -> str:
        if self.base_url:
            return ep.path_url_for(endpoint_key, self.base_url, **path_params)
        return ep.url_for(endpoint_key, region=self.region, **path_params)

    def _request_once(self, endpoint_key: str, *, body: dict | None = None, **path_params: str) -> httpx.Response:
        endpoint = ep.endpoint(endpoint_key)
        kwargs: dict[str, Any] = {"headers": self.headers(), "timeout": self.timeout_s}
        if body is not None:
            kwargs["json"] = body
        return httpx.request(endpoint.method.upper(), self.url(endpoint_key, **path_params), **kwargs)

    def _call(self, endpoint_key: str, *, body: dict | None = None, **path_params: str):
        ep.endpoint(endpoint_key)
        rate_limit.acquire(endpoint_key)
        last_error: Exception | None = None
        for attempt in range(rate_limit.MAX_ATTEMPTS):
            try:
                response = self._request_once(endpoint_key, body=body, **path_params)
            except httpx.HTTPError as exc:
                last_error = exc
                if endpoint_key in rate_limit.NON_RETRYABLE_ENDPOINTS:
                    raise
                time.sleep(rate_limit.backoff_sleep(attempt))
                continue
            if response.status_code == 401 and attempt == 0:
                self._access_token = None
                self._access_expires_at = None
                continue
            if response.status_code == 429:
                if endpoint_key in rate_limit.NON_RETRYABLE_ENDPOINTS:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                time.sleep(rate_limit.backoff_sleep(attempt, float(retry_after) if retry_after else None))
                continue
            if 500 <= response.status_code < 600 and endpoint_key not in rate_limit.NON_RETRYABLE_ENDPOINTS:
                time.sleep(rate_limit.backoff_sleep(attempt))
                continue
            response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return response.text
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"SP-API request failed after {rate_limit.MAX_ATTEMPTS} attempts: {endpoint_key}")

    @staticmethod
    def check_history(start: dt.date) -> None:
        oldest = dt.date.today() - dt.timedelta(days=MAX_REPORT_HISTORY_DAYS)
        if start < oldest:
            raise ReportHistoryExceeded(f"SP-API reports go back ~2 years (oldest: {oldest}, requested: {start})")

    @staticmethod
    def check_report_type(report_type: str) -> None:
        if report_type not in ep.SP_REPORT_TYPES:
            raise UnknownReportType(f"'{report_type}' is not in SP_REPORT_TYPES. Known types: {sorted(ep.SP_REPORT_TYPES)}")

    @staticmethod
    def check_attribution_granularity(report_type: str, report_options: dict | None) -> None:
        if report_type != SALES_AND_TRAFFIC:
            return
        options = report_options or {}
        if options.get("asinGranularity") != "CHILD":
            raise AttributionGranularityError(f"{SALES_AND_TRAFFIC} requires asinGranularity='CHILD'")
        if options.get("dateGranularity") != "DAY":
            raise AttributionGranularityError(f"{SALES_AND_TRAFFIC} requires dateGranularity='DAY'")

    def create_report(self, report_type: str, start: dt.date, end: dt.date, report_options: dict | None = None) -> str:
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
        rate_limit.acquire_report_type(report_type)
        result = self._call("sp.reports.create", body=body)
        return str(result.get("reportId") or result.get("report_id") or result.get("id"))

    def wait_for_report(self, report_id: str, timeout_s: int = 3600) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self._call("sp.reports.get", reportId=report_id)
            status = str(result.get("processingStatus") or result.get("status") or "").upper()
            if status in {"DONE", "SUCCESS", "COMPLETED"}:
                document_id = result.get("reportDocumentId") or result.get("documentId")
                if not document_id:
                    raise RuntimeError(f"SP-API report {report_id} finished without document id")
                return str(document_id)
            if status in {"FATAL", "CANCELLED", "FAILED"}:
                raise RuntimeError(f"SP-API report {report_id} failed: {result}")
            time.sleep(15)
        raise TimeoutError(f"SP-API report {report_id} did not finish within {timeout_s}s")

    def get_report_document(self, document_id: str) -> dict:
        return self._call("sp.reports.document", reportDocumentId=document_id)

    def download_report(self, document_id: str) -> bytes:
        doc = self.get_report_document(document_id)
        url = doc.get("url") or doc.get("downloadUrl")
        if not url:
            raise RuntimeError(f"SP-API document {document_id} did not include a download URL")
        response = httpx.get(str(url), follow_redirects=True, timeout=self.timeout_s)
        response.raise_for_status()
        return response.content

    def get_inventory_summaries(self) -> dict:
        return self._call("sp.inventory.summaries")


SALES_AND_TRAFFIC = "GET_SALES_AND_TRAFFIC_REPORT"
BRAND_ANALYTICS_SEARCH_TERMS = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"
BRAND_ANALYTICS_CATALOG_PERFORMANCE = "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT"
