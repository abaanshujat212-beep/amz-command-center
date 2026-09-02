"""Amazon Ads API client wrapper."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import httpx

from packages.shared import endpoints as ep
from packages.shared.marketplaces import DEFAULT, Marketplace
from services.ingest.clients import rate_limit


class LookbackExceeded(ValueError):
    """Raised when a requested date is older than Amazon will serve."""


class AdsAuthError(RuntimeError):
    pass


class NotAWriteEndpoint(RuntimeError):
    """A read endpoint was about to be used to change a client's account."""


@dataclass
class AdsCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    profile_id: int | None = None


class AdsClient:
    """Thin, swappable wrapper. Pipelines must never import the vendor SDK."""

    def __init__(
        self,
        credentials: AdsCredentials,
        marketplace: Marketplace = DEFAULT,
        tenant_id: str | None = None,
        region: str = ep.DEFAULT_REGION,
        timeout_s: float = 60.0,
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id
        self.region = region
        self.timeout_s = timeout_s
        self._access_token: str | None = None
        self._access_expires_at: dt.datetime | None = None

    @property
    def token_url(self) -> str:
        return ep.REGIONS[self.region].ads_token_url

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
            raise AdsAuthError(f"Ads token refresh failed: HTTP {response.status_code}")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise AdsAuthError("Ads token refresh response did not include access_token")
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
        h = {
            "Authorization": f"Bearer {self.access_token}",
            "Amazon-Advertising-API-ClientId": self.credentials.client_id,
            "Content-Type": "application/json",
        }
        if self.credentials.profile_id:
            h["Amazon-Advertising-API-Scope"] = str(self.credentials.profile_id)
        return h

    def url(self, endpoint_key: str, **path_params: str) -> str:
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
        raise RuntimeError(f"Ads request failed after {rate_limit.MAX_ATTEMPTS} attempts: {endpoint_key}")

    def _call_mutating(self, endpoint_key: str, *, body: dict, **path_params: str):
        endpoint = ep.endpoint(endpoint_key)
        if not endpoint.mutates:
            raise NotAWriteEndpoint(
                f"{endpoint_key} is not marked mutates=True in the endpoint catalog. "
                f"The complete write blast radius is: {sorted(e.key for e in ep.mutating())}"
            )
        return self._call(endpoint_key, body=body, **path_params)

    def list_profiles(self) -> list[dict]:
        return self._call("ads.profiles.list")

    def list_campaigns(self, next_token: str | None = None, campaign_ids: list[str] | None = None) -> dict:
        body: dict = {"maxResults": 500}
        if next_token:
            body["nextToken"] = next_token
        if campaign_ids:
            body["campaignIdFilter"] = {"include": campaign_ids}
        return self._call("ads.campaigns.list", body=body)

    def list_keywords(self, campaign_ids: list[str] | None = None, keyword_ids: list[str] | None = None) -> dict:
        body: dict = {"maxResults": 500}
        if campaign_ids:
            body["campaignIdFilter"] = {"include": campaign_ids}
        if keyword_ids:
            body["keywordIdFilter"] = {"include": keyword_ids}
        return self._call("ads.keywords.list", body=body)

    def list_targets(self, target_ids: list[str] | None = None) -> dict:
        body: dict = {"maxResults": 500}
        if target_ids:
            body["targetIdFilter"] = {"include": target_ids}
        return self._call("ads.targets.list", body=body)

    def keyword_bid(self, keyword_id: str) -> dict:
        result = self.list_keywords(keyword_ids=[keyword_id])
        keywords = result.get("keywords") or result.get("keywordResponse") or []
        for keyword in keywords:
            if str(keyword.get("keywordId")) == str(keyword_id):
                return {"value": keyword.get("bid")}
        raise RuntimeError(f"keyword {keyword_id} was not returned by Ads API")

    def target_bid(self, target_id: str) -> dict:
        result = self.list_targets(target_ids=[target_id])
        targets = result.get("targets") or result.get("targetingClauses") or []
        for target in targets:
            if str(target.get("targetId") or target.get("targetingId")) == str(target_id):
                return {"value": target.get("bid")}
        raise RuntimeError(f"target {target_id} was not returned by Ads API")

    def placement_modifier(self, campaign_id: str, placement_api_enum: str) -> dict:
        result = self.list_campaigns(campaign_ids=[campaign_id])
        campaigns = result.get("campaigns") or result.get("campaignResponse") or []
        for campaign in campaigns:
            if str(campaign.get("campaignId")) != str(campaign_id):
                continue
            bidding = campaign.get("dynamicBidding") or {}
            for placement in bidding.get("placementBidding") or []:
                if placement.get("placement") == placement_api_enum:
                    return {"value": placement.get("percentage"), "placement": placement_api_enum}
            return {"value": 0, "placement": placement_api_enum}
        raise RuntimeError(f"campaign {campaign_id} was not returned by Ads API")

    @staticmethod
    def check_lookback(report_kind: str, start_date: dt.date) -> None:
        limit = ep.lookback_days(report_kind)
        oldest = dt.date.today() - dt.timedelta(days=limit)
        if start_date < oldest:
            raise LookbackExceeded(
                f"{report_kind} only goes back {limit} days (oldest available: {oldest}, requested: {start_date}). "
                "Those days are gone permanently — this is why ingestion runs daily."
            )

    def create_report(self, report_kind: str, start_date: dt.date, end_date: dt.date, group_by: tuple[str, ...] = ()) -> str:
        self.check_lookback(report_kind, start_date)
        if not group_by:
            raise ValueError(f"{report_kind}: group_by is required — it decides the grain of the rows")
        if end_date < start_date:
            raise ValueError(f"end_date {end_date} is before start_date {start_date}")
        body = {
            "name": f"{report_kind}-{start_date}-{end_date}",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS",
                "reportTypeId": report_kind,
                "groupBy": list(group_by),
                "timeUnit": "DAILY",
                "format": "GZIP_JSON",
            },
        }
        result = self._call("ads.reports.create", body=body)
        return str(result.get("reportId") or result.get("report_id") or result.get("id"))

    def wait_for_report(self, report_id: str, timeout_s: int = 1800) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self._call("ads.reports.get", reportId=report_id)
            status = str(result.get("status") or result.get("processingStatus") or "").upper()
            if status in {"SUCCESS", "COMPLETED", "DONE"}:
                location = result.get("url") or result.get("location") or result.get("downloadUrl")
                if not location:
                    raise RuntimeError(f"Ads report {report_id} completed without a download URL")
                return str(location)
            if status in {"FAILURE", "FAILED", "CANCELLED"}:
                raise RuntimeError(f"Ads report {report_id} failed: {result}")
            time.sleep(15)
        raise TimeoutError(f"Ads report {report_id} did not finish within {timeout_s}s")

    def download_report(self, url: str) -> bytes:
        response = httpx.get(url, follow_redirects=True, timeout=self.timeout_s)
        response.raise_for_status()
        return response.content

    def update_bid(self, entity_id: str, new_bid: float, dry_run: bool = True) -> dict:
        if dry_run:
            return {"status": "WOULD_DO", "entity_id": entity_id, "bid": new_bid}
        body = {"keywords": [{"keywordId": entity_id, "bid": new_bid}]}
        return self._call_mutating("ads.keywords.update", body=body)

    def update_target_bid(self, target_id: str, new_bid: float, dry_run: bool = True) -> dict:
        if dry_run:
            return {"status": "WOULD_DO", "entity_id": target_id, "bid": new_bid}
        body = {"targetingClauses": [{"targetId": target_id, "bid": new_bid}]}
        return self._call_mutating("ads.targets.update", body=body)

    def update_placement_modifier(self, campaign_id: str, placement_api_enum: str, new_percentage: float, current_percentage: float | None, dry_run: bool = True) -> dict:
        if placement_api_enum not in PLACEMENT_BID_ENUMS:
            raise ValueError(f"unknown placement enum '{placement_api_enum}'. Valid: {sorted(PLACEMENT_BID_ENUMS)}")
        if current_percentage is None:
            raise ValueError(f"campaign {campaign_id}: refusing to set {placement_api_enum} to {new_percentage}% without knowing the current modifier (#32)")
        if dry_run:
            return {"status": "WOULD_DO", "campaign_id": campaign_id, "placement": placement_api_enum, "from": current_percentage, "to": new_percentage}
        body = {
            "campaigns": [
                {
                    "campaignId": campaign_id,
                    "dynamicBidding": {"placementBidding": [{"placement": placement_api_enum, "percentage": new_percentage}]},
                }
            ]
        }
        return self._call_mutating("ads.campaigns.update", body=body)


PLACEMENT_BID_ENUMS = frozenset({"PLACEMENT_TOP", "PLACEMENT_PRODUCT_PAGE", "PLACEMENT_REST_OF_SEARCH"})
