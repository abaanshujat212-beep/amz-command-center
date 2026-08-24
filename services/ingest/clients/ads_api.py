"""Amazon Ads API client wrapper.

Designed for many advertiser accounts under ONE LWA application: approval is
granted to our client app, and each advertiser has its own refresh token. The
tenant_id decides which token is used — there is no global token.

Every request is built from packages/shared/endpoints.py. No path is written as
an f-string here, which is what makes "the copilot knows every endpoint" a
verifiable claim instead of a promise: if it is not in the catalog, this client
cannot call it (see tests/test_endpoint_discipline.py).

Lookback limits are NOT redefined here. They used to be, and the copy drifted
ahead of the catalog within days.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from packages.shared import endpoints as ep
from packages.shared.marketplaces import DEFAULT, Marketplace


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
    ) -> None:
        self.credentials = credentials
        self.marketplace = marketplace
        self.tenant_id = tenant_id
        self.region = region
        self._access_token: str | None = None
        self._access_expires_at: dt.datetime | None = None

    # ---------------------------------------------------------------- auth
    @property
    def token_url(self) -> str:
        """Ads LWA token endpoint is region-specific, unlike SP-API's."""
        return ep.REGIONS[self.region].ads_token_url

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

    # ------------------------------------------------------- request seam
    def url(self, endpoint_key: str, **path_params: str) -> str:
        """The only way a URL is produced in this class."""
        return ep.url_for(endpoint_key, region=self.region, **path_params)

    def _call(self, endpoint_key: str, *, body: dict | None = None, **path_params: str):
        """Single dispatch point. Every request passes through here.

        Deliberately one function: retry, Retry-After handling, redaction and
        rate limiting must exist in exactly one place. Ads API rate limits are
        dynamic and undocumented per endpoint, so the only correct behaviour is
        to honour Retry-After on 429 rather than to pace by a guessed constant.

        Logs must redact 'Atzr|' and 'Atza|' prefixed tokens — an access token in
        a log line is a credential leak that looks like debugging output.
        """
        endpoint = ep.endpoint(endpoint_key)  # raises if uncatalogued
        _ = self.url(endpoint_key, **path_params)
        _ = endpoint.method
        raise NotImplementedError("HTTP layer lands with M0-06")

    def _call_mutating(self, endpoint_key: str, *, body: dict, **path_params: str):
        """Same as _call, but refuses if the endpoint is not a declared writer.

        Guards against the quiet version of this mistake: using a read endpoint
        for a write would either 405 or, worse, succeed against something else.
        """
        endpoint = ep.endpoint(endpoint_key)
        if not endpoint.mutates:
            raise NotAWriteEndpoint(
                f"{endpoint_key} is not marked mutates=True in the endpoint catalog. "
                f"The complete write blast radius is: "
                f"{sorted(e.key for e in ep.mutating())}"
            )
        return self._call(endpoint_key, body=body, **path_params)

    # ------------------------------------------------------------ profiles
    def list_profiles(self) -> list[dict]:
        """Advertiser profiles. The wrong profileId edits the wrong client."""
        return self._call("ads.profiles.list")

    def list_campaigns(self, next_token: str | None = None) -> dict:
        """Campaigns incl. dynamicBidding, which is where placement modifiers live.

        Needed by #32. Until this is ingested, placement_modifier_pct stays NULL
        and the placement rule diagnoses only (ADR 005).
        """
        body: dict = {"maxResults": 500}
        if next_token:
            body["nextToken"] = next_token
        return self._call("ads.campaigns.list", body=body)

    def list_keywords(self, campaign_ids: list[str] | None = None) -> dict:
        """Current bids, used to re-read before_value at apply time."""
        body: dict = {"maxResults": 500}
        if campaign_ids:
            body["campaignIdFilter"] = {"include": campaign_ids}
        return self._call("ads.keywords.list", body=body)

    # ------------------------------------------------------------- reports
    @staticmethod
    def check_lookback(report_kind: str, start_date: dt.date) -> None:
        """Refuse a window Amazon cannot serve.

        Raises ep.UnknownReportKind for an unlisted kind rather than assuming a
        window. Assuming 95 days for a 60-day report returns a SHORTER window
        with no error, and the missing days expire permanently.
        """
        limit = ep.lookback_days(report_kind)
        oldest = dt.date.today() - dt.timedelta(days=limit)
        if start_date < oldest:
            raise LookbackExceeded(
                f"{report_kind} only goes back {limit} days "
                f"(oldest available: {oldest}, requested: {start_date}). "
                "Those days are gone permanently — this is why ingestion runs daily."
            )

    def create_report(
        self,
        report_kind: str,
        start_date: dt.date,
        end_date: dt.date,
        group_by: tuple[str, ...] = (),
    ) -> str:
        """Request a report and return its id.

        group_by is the report's GRAIN, and it is not optional: reporting v3
        rejects a configuration without one, and two of our datasets differ by
        nothing else. spCampaigns grouped by ('campaign',) is the campaign
        report; grouped by ('campaign', 'campaignPlacement') it is the placement
        report. Defaulting it would land campaign-grain rows in the placement
        table, where every placement would look like 100% of the campaign.
        """
        self.check_lookback(report_kind, start_date)
        if not group_by:
            raise ValueError(
                f"{report_kind}: group_by is required — it decides the grain of the "
                "rows, and the wrong grain is worse than no rows. See "
                "services/ingest/pipelines/ads_daily.py DATASETS."
            )
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
        return self._call("ads.reports.create", body=body)

    def wait_for_report(self, report_id: str, timeout_s: int = 1800) -> str:
        """Poll until COMPLETED, then return the download URL.

        Note: v2 downloads answer 307 with an S3 link that expires in ~30
        seconds, so follow the redirect immediately. The URL must never be
        persisted — a stored link fails later in a way that looks like a data gap.
        """
        _ = self.url("ads.reports.get", reportId=report_id)
        return self._call("ads.reports.get", reportId=report_id)

    def download_report(self, url: str) -> bytes:
        """Fetch a report payload from a pre-signed URL.

        Not an endpoint call: the URL comes from Amazon, not from the catalog,
        which is why it does not go through _call.
        """
        raise NotImplementedError("see M0-06")

    # ------------------------------------------------------------ mutation
    def update_bid(self, entity_id: str, new_bid: float, dry_run: bool = True) -> dict:
        """Write-back is gated: guardrails live in services/actions (M4-21, M5-22)."""
        if dry_run:
            return {"status": "WOULD_DO", "entity_id": entity_id, "bid": new_bid}
        body = {"keywords": [{"keywordId": entity_id, "bid": new_bid}]}
        return self._call_mutating("ads.keywords.update", body=body)

    def update_placement_modifier(
        self,
        campaign_id: str,
        placement_api_enum: str,
        new_percentage: float,
        current_percentage: float | None,
        dry_run: bool = True,
    ) -> dict:
        """Placement bid adjustment on a campaign's dynamicBidding.

        current_percentage must be read from Amazon, not assumed. A placement
        modifier is a percentage on top of whatever is already set, and nothing
        ingests the existing value yet (#32) — so this refuses rather than
        computing a change from an assumed 0% and wiping a modifier the seller
        set by hand.
        """
        if placement_api_enum not in PLACEMENT_BID_ENUMS:
            raise ValueError(
                f"unknown placement enum '{placement_api_enum}'. Valid: "
                f"{sorted(PLACEMENT_BID_ENUMS)}. Off-Amazon placements have no "
                "multiplier at all, so they can be diagnosed but never adjusted."
            )
        if current_percentage is None:
            raise ValueError(
                f"campaign {campaign_id}: refusing to set {placement_api_enum} to "
                f"{new_percentage}% without knowing the current modifier (#32)"
            )
        if dry_run:
            return {
                "status": "WOULD_DO",
                "campaign_id": campaign_id,
                "placement": placement_api_enum,
                "from": current_percentage,
                "to": new_percentage,
            }
        # There is no placement endpoint: the modifier is a field on the
        # campaign object. See ADR 005.
        body = {
            "campaigns": [
                {
                    "campaignId": campaign_id,
                    "dynamicBidding": {
                        "placementBidding": [
                            {
                                "placement": placement_api_enum,
                                "percentage": new_percentage,
                            }
                        ]
                    },
                }
            ]
        }
        return self._call_mutating("ads.campaigns.update", body=body)


# The three placements that accept a bid multiplier. Off-Amazon traffic appears
# in reports but cannot be adjusted, which is why the placement rule is
# diagnosis-only for it (ADR 005).
PLACEMENT_BID_ENUMS = frozenset(
    {"PLACEMENT_TOP", "PLACEMENT_PRODUCT_PAGE", "PLACEMENT_REST_OF_SEARCH"}
)
