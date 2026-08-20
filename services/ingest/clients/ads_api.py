"""Amazon Ads API client wrapper.

Designed for many advertiser accounts under ONE LWA application: approval is
granted to our client app, and each advertiser has its own refresh token. The
tenant_id decides which token is used — there is no global token.

Hard limits encoded here:
  Sponsored Products / SB v3 ......... ~95 days lookback
  Sponsored Display / SB v2 ..........  60 days
  SB_BENCHMARK .......................  90 days
A request older than the limit raises instead of quietly returning nothing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from packages.shared.marketplaces import DEFAULT, Marketplace

LOOKBACK_DAYS: dict[str, int] = {
    "spCampaigns": 95,
    "spAdGroups": 95,
    "spTargeting": 95,
    "spSearchTerm": 95,
    "spAdvertisedProduct": 95,
    "spPurchasedProduct": 95,
    "sbV3": 95,
    "sbBenchmark": 90,
    "sbV2": 60,
    "sdCampaigns": 60,
}


class LookbackExceeded(ValueError):
    """Raised when a requested date is older than Amazon will serve."""


class AdsAuthError(RuntimeError):
    pass


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
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id
        self._access_token: str | None = None
        self._access_expires_at: dt.datetime | None = None

    # ---------------------------------------------------------------- auth
    def _refresh_access_token(self) -> str:
        """Exchange the refresh token. Access tokens last ~60 minutes.

        Amazon may return a NEW refresh token; the caller must persist it via
        the vault. Losing a rotated refresh token means re-authorization.
        """
        raise NotImplementedError("implement with python-amazon-ad-api (see M0-06)")

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

    # ------------------------------------------------------------ profiles
    def list_profiles(self) -> list[dict]:
        """GET /v2/profiles — find the UK profile (countryCode GB, currency GBP)."""
        raise NotImplementedError("see M0-06")

    # ------------------------------------------------------------- reports
    @staticmethod
    def check_lookback(report_kind: str, start_date: dt.date) -> None:
        limit = LOOKBACK_DAYS.get(report_kind)
        if limit is None:
            raise ValueError(f"unknown report kind: {report_kind}")
        oldest = dt.date.today() - dt.timedelta(days=limit)
        if start_date < oldest:
            raise LookbackExceeded(
                f"{report_kind} only goes back {limit} days "
                f"(oldest available: {oldest}, requested: {start_date}). "
                "Those days are gone permanently — this is why ingestion runs daily."
            )

    def create_report(self, report_kind: str, start_date: dt.date, end_date: dt.date) -> str:
        self.check_lookback(report_kind, start_date)
        raise NotImplementedError("see M0-06")

    def wait_for_report(self, report_id: str, timeout_s: int = 1800) -> str:
        """Poll until COMPLETED, then return the download URL.

        Note: v2 downloads answer 307 with an S3 link that expires in ~30
        seconds, so follow the redirect immediately.
        """
        raise NotImplementedError("see M0-06")

    def download_report(self, url: str) -> bytes:
        raise NotImplementedError("see M0-06")

    # ------------------------------------------------------------ mutation
    def update_bid(self, entity_id: str, new_bid: float, dry_run: bool = True) -> dict:
        """Write-back is gated: guardrails live in services/actions (M4-21, M5-22)."""
        if dry_run:
            return {"status": "WOULD_DO", "entity_id": entity_id, "bid": new_bid}
        raise NotImplementedError("write-back lands in M5-22, not before")
