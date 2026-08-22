"""Every Amazon endpoint this system may call — as data, in one place.

Why this module exists
----------------------
The clients build their requests from this catalog, and the System Copilot (#33)
reads the same dict to answer questions about the system. The alternative — a
document listing endpoints while the clients call them separately — drifts within
a week, and then the copilot confidently quotes the document.

So: if an endpoint is not here, the client cannot call it either. A gap shows up
as a failure instead of as a wrong answer.

Nothing in this module performs I/O, reads credentials, or imports a client. It is
safe to import from tests, from the copilot, and from a cold process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Api(str, Enum):
    SP_API = "sp_api"
    ADS = "ads"


@dataclass(frozen=True)
class Region:
    """Hosts differ per region and are a classic source of silent 403s."""

    code: str
    sp_host: str
    ads_host: str
    ads_token_url: str
    ads_auth_host: str


# We operate in EU (Amazon UK). The others are listed so the copilot can answer
# "what changes if we add a US client?" without anyone guessing.
REGIONS: dict[str, Region] = {
    "eu": Region(
        code="eu",
        sp_host="https://sellingpartnerapi-eu.amazon.com",
        ads_host="https://advertising-api-eu.amazon.com",
        ads_token_url="https://api.amazon.co.uk/auth/o2/token",
        ads_auth_host="https://eu.account.amazon.com/ap/oa",
    ),
    "na": Region(
        code="na",
        sp_host="https://sellingpartnerapi-na.amazon.com",
        ads_host="https://advertising-api.amazon.com",
        ads_token_url="https://api.amazon.com/auth/o2/token",
        ads_auth_host="https://www.amazon.com/ap/oa",
    ),
    "fe": Region(
        code="fe",
        sp_host="https://sellingpartnerapi-fe.amazon.com",
        ads_host="https://advertising-api-fe.amazon.com",
        ads_token_url="https://api.amazon.co.jp/auth/o2/token",
        ads_auth_host="https://apac.account.amazon.com/ap/oa",
    ),
}

DEFAULT_REGION = "eu"

# LWA is not region-specific for SP-API, unlike Ads.
SP_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


@dataclass(frozen=True)
class Endpoint:
    key: str
    api: Api
    method: str
    path: str
    summary: str
    # None means Amazon does not publish a fixed rate for this endpoint. Ads API
    # is dynamic: the only correct behaviour is to honour Retry-After on 429.
    rate_limit_rps: float | None = None
    burst: int | None = None
    # True only when calling this changes something on the seller's account.
    # Creating a report is a POST but changes nothing, so it is False.
    mutates: bool = False
    scope: str | None = None
    notes: str = ""


def _e(*args, **kwargs) -> tuple[str, Endpoint]:
    ep = Endpoint(*args, **kwargs)
    return ep.key, ep


ENDPOINTS: dict[str, Endpoint] = dict(
    [
        # --- SP-API: reports -------------------------------------------------
        _e(
            "sp.reports.create",
            Api.SP_API,
            "POST",
            "/reports/2021-06-30/reports",
            "Request a report; returns a reportId, not data.",
            rate_limit_rps=0.0222,
            burst=10,
            notes="0.0222 rps is one request per 45s. Batch report requests, never loop.",
        ),
        _e(
            "sp.reports.get",
            Api.SP_API,
            "GET",
            "/reports/2021-06-30/reports/{reportId}",
            "Poll report status until DONE.",
            rate_limit_rps=2.0,
            burst=15,
        ),
        _e(
            "sp.reports.document",
            Api.SP_API,
            "GET",
            "/reports/2021-06-30/documents/{reportDocumentId}",
            "Get the (usually gzipped) document URL for a finished report.",
            rate_limit_rps=0.0167,
            burst=15,
            notes="The returned URL is short-lived. Download immediately, do not persist it.",
        ),
        # --- SP-API: other ---------------------------------------------------
        _e(
            "sp.orders.list",
            Api.SP_API,
            "GET",
            "/orders/v0/orders",
            "Orders, for reconciliation against ad-attributed sales.",
            rate_limit_rps=0.0167,
            burst=20,
        ),
        _e(
            "sp.catalog.item",
            Api.SP_API,
            "GET",
            "/catalog/2022-04-01/items/{asin}",
            "Catalog attributes for an ASIN.",
            rate_limit_rps=5.0,
            burst=40,
        ),
        _e(
            "sp.inventory.summaries",
            Api.SP_API,
            "GET",
            "/fba/inventory/v1/summaries",
            "FBA inventory; needed before recommending a budget increase.",
            rate_limit_rps=2.0,
            burst=30,
            notes="Scaling spend on an out-of-stock ASIN is the most expensive avoidable mistake.",
        ),
        _e(
            "sp.finances.events",
            Api.SP_API,
            "GET",
            "/finances/v0/financialEvents",
            "Fees and settlements, to validate the cost ledger against reality.",
            rate_limit_rps=0.5,
            burst=30,
        ),
        _e(
            "sp.tokens.rdt",
            Api.SP_API,
            "POST",
            "/tokens/2021-03-01/restrictedDataToken",
            "Restricted Data Token, required before reading any PII.",
            rate_limit_rps=1.0,
            burst=10,
            notes="We avoid PII entirely for now, so this should stay unused. If it starts "
            "being called, that is a scope change and needs a DPA review.",
        ),
        # --- Ads API: reporting v3 ------------------------------------------
        _e(
            "ads.reports.create",
            Api.ADS,
            "POST",
            "/reporting/reports",
            "Request an async v3 report.",
            scope="advertising::campaign_management",
            notes="Body carries reportTypeId, groupBy, columns and the date window. "
            "groupBy is what distinguishes campaign grain from placement grain.",
        ),
        _e(
            "ads.reports.get",
            Api.ADS,
            "GET",
            "/reporting/reports/{reportId}",
            "Poll report status; SUCCESS returns a download URL.",
            scope="advertising::campaign_management",
            notes="v2 returned a 307 to an S3 link expiring in ~30s. Download in the same breath.",
        ),
        # --- Ads API: account -----------------------------------------------
        _e(
            "ads.profiles.list",
            Api.ADS,
            "GET",
            "/v2/profiles",
            "Advertiser profiles; the profileId scopes every other Ads call.",
            scope="advertising::campaign_management",
            notes="One LWA app can see many advertisers. Sending the wrong profileId edits "
            "the wrong client's account, and the API will happily accept it.",
        ),
        # --- Ads API: read -----------------------------------------------
        _e(
            "ads.campaigns.list",
            Api.ADS,
            "POST",
            "/sp/campaigns/list",
            "List Sponsored Products campaigns, including dynamicBidding config.",
            scope="advertising::campaign_management",
            notes="This is where placement bid adjustments live. Needed by #32; until it is "
            "ingested, placement_modifier_pct stays NULL by design.",
        ),
        _e(
            "ads.adGroups.list",
            Api.ADS,
            "POST",
            "/sp/adGroups/list",
            "List ad groups.",
            scope="advertising::campaign_management",
        ),
        _e(
            "ads.keywords.list",
            Api.ADS,
            "POST",
            "/sp/keywords/list",
            "List keywords with current bids.",
            scope="advertising::campaign_management",
            notes="Used to re-read before_value at apply time, so a human's manual change "
            "is detected as drift instead of being silently overwritten.",
        ),
        # --- Ads API: mutating ----------------------------------------------
        _e(
            "ads.campaigns.update",
            Api.ADS,
            "PUT",
            "/sp/campaigns",
            "Update campaign budget, state, or placement bid adjustments.",
            mutates=True,
            scope="advertising::campaign_management",
            notes="There is no separate placement endpoint: placement modifiers are a field "
            "on the campaign (dynamicBidding.placementBidding). See ADR 005.",
        ),
        _e(
            "ads.adGroups.update",
            Api.ADS,
            "PUT",
            "/sp/adGroups",
            "Update ad group state or default bid.",
            mutates=True,
            scope="advertising::campaign_management",
        ),
        _e(
            "ads.keywords.update",
            Api.ADS,
            "PUT",
            "/sp/keywords",
            "Update keyword bid or state.",
            mutates=True,
            scope="advertising::campaign_management",
        ),
        _e(
            "ads.keywords.create",
            Api.ADS,
            "POST",
            "/sp/keywords",
            "Create keywords (search-term harvesting).",
            mutates=True,
            scope="advertising::campaign_management",
        ),
        _e(
            "ads.targets.update",
            Api.ADS,
            "PUT",
            "/sp/targets",
            "Update product/auto targeting expressions.",
            mutates=True,
            scope="advertising::campaign_management",
        ),
        _e(
            "ads.negativeKeywords.create",
            Api.ADS,
            "POST",
            "/sp/negativeKeywords",
            "Add negative exact / negative phrase keywords.",
            mutates=True,
            scope="advertising::campaign_management",
            notes="Cheapest irreversible-feeling action: easy to add, easy to forget, and it "
            "suppresses traffic silently. Always logged with the search term that caused it.",
        ),
    ]
)


# --- Report kinds and their true history windows --------------------------
#
# The lookback is not a preference, it is a hard wall. Un-ingested days past it
# are gone permanently, for everyone, forever.
ADS_REPORT_LOOKBACK_DAYS: dict[str, int] = {
    "spCampaigns": 95,
    "spTargeting": 95,
    "spSearchTerm": 95,
    "spAdvertisedProduct": 95,
    "spPurchasedProduct": 95,
    "sbBenchmark": 90,
    "sbV2": 60,
    "sdCampaigns": 60,
}

SP_REPORT_TYPES: dict[str, str] = {
    "GET_SALES_AND_TRAFFIC_REPORT": "Sessions, page views, unit session percentage. "
    "Max 3 requests per 5 minutes; dataStartTime within 2 years; asinGranularity=CHILD.",
    "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT": "SQP search terms, weekly (Sun-Sat). "
    "Requires Brand Analytics role and brand registration.",
    "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT": "Per-ASIN search funnel.",
    "GET_COUPON_PERFORMANCE_REPORT": "Coupon spend, for true promotional cost.",
}


# --- action_type -> the endpoint that would carry it out -------------------
#
# Keys must stay in step with the action_action_type_check constraint (0006).
# tests/test_system_map.py enforces that; do not let this drift.
#
# Nested by scope because "pause" means a different endpoint for a campaign than
# for a keyword, and picking the wrong one edits the wrong object.
ACTION_ENDPOINTS: dict[str, dict[str, str]] = {
    "set_bid": {
        "keyword": "ads.keywords.update",
        "target": "ads.targets.update",
        "ad_group": "ads.adGroups.update",
    },
    "set_budget": {"campaign": "ads.campaigns.update"},
    "pause": {
        "campaign": "ads.campaigns.update",
        "ad_group": "ads.adGroups.update",
        "keyword": "ads.keywords.update",
        "target": "ads.targets.update",
    },
    "enable": {
        "campaign": "ads.campaigns.update",
        "ad_group": "ads.adGroups.update",
        "keyword": "ads.keywords.update",
        "target": "ads.targets.update",
    },
    "add_negative_exact": {
        "campaign": "ads.negativeKeywords.create",
        "ad_group": "ads.negativeKeywords.create",
        "search_term": "ads.negativeKeywords.create",
    },
    "add_negative_phrase": {
        "campaign": "ads.negativeKeywords.create",
        "ad_group": "ads.negativeKeywords.create",
        "search_term": "ads.negativeKeywords.create",
    },
    "create_keyword": {
        "ad_group": "ads.keywords.create",
        "search_term": "ads.keywords.create",
    },
    "set_placement_modifier": {"campaign": "ads.campaigns.update"},
    # Diagnostics never leave the database. This empty mapping is the point:
    # there is no endpoint a flag could ever reach, by construction.
    "flag": {},
}

LOCAL_ONLY_ACTIONS = frozenset({"flag"})


class UnknownEndpoint(KeyError):
    pass


def endpoint(key: str) -> Endpoint:
    try:
        return ENDPOINTS[key]
    except KeyError:
        raise UnknownEndpoint(
            f"'{key}' is not in the endpoint catalog. Add it to "
            f"packages/shared/endpoints.py rather than hardcoding a path."
        ) from None


def for_api(api: Api) -> list[Endpoint]:
    return [e for e in ENDPOINTS.values() if e.api == api]


def mutating() -> list[Endpoint]:
    """The complete blast radius: every call that can change a client's account."""
    return [e for e in ENDPOINTS.values() if e.mutates]


def endpoint_for_action(action_type: str, scope: str) -> Endpoint | None:
    """Which endpoint an action would use. None means it never leaves the DB."""
    if action_type not in ACTION_ENDPOINTS:
        raise UnknownEndpoint(
            f"action_type '{action_type}' has no entry in ACTION_ENDPOINTS. If it is a "
            f"new action, map it (or add it to LOCAL_ONLY_ACTIONS) before shipping."
        )
    if action_type in LOCAL_ONLY_ACTIONS:
        return None
    key = ACTION_ENDPOINTS[action_type].get(scope)
    if key is None:
        return None
    return endpoint(key)


def host_for(api: Api, region: str = DEFAULT_REGION) -> str:
    r = REGIONS[region]
    return r.sp_host if api == Api.SP_API else r.ads_host


def url_for(key: str, region: str = DEFAULT_REGION, **path_params: str) -> str:
    """Build a full URL from the catalog. Clients should use this, not f-strings."""
    ep = endpoint(key)
    path = ep.path
    for name, value in path_params.items():
        path = path.replace("{" + name + "}", str(value))
    if "{" in path:
        missing = path[path.index("{") :].split("}")[0].strip("{")
        raise ValueError(f"{key} needs path parameter '{missing}'")
    return host_for(ep.api, region) + path


def catalogued_paths(api: Api) -> set[str]:
    """Used by tests to assert no client builds a path that is not catalogued."""
    return {e.path for e in for_api(api)}
