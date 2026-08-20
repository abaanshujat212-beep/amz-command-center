"""Marketplace and endpoint constants. UK-first; do not hardcode elsewhere."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Marketplace:
    marketplace_id: str
    country_code: str
    currency: str
    spapi_endpoint: str
    ads_endpoint: str
    ads_token_url: str
    ads_auth_host: str
    timezone: str


UK = Marketplace(
    marketplace_id="A1F83G8C2ARO7P",
    country_code="GB",
    currency="GBP",
    spapi_endpoint="https://sellingpartnerapi-eu.amazon.com",
    ads_endpoint="https://advertising-api-eu.amazon.com",
    ads_token_url="https://api.amazon.co.uk/auth/o2/token",
    ads_auth_host="https://eu.account.amazon.com",
    timezone="Europe/London",
)

# Phase 6+ only. Adding a marketplace must not require touching pipeline code.
DE = Marketplace(
    marketplace_id="A1PA6795UKMFR9",
    country_code="DE",
    currency="EUR",
    spapi_endpoint="https://sellingpartnerapi-eu.amazon.com",
    ads_endpoint="https://advertising-api-eu.amazon.com",
    ads_token_url="https://api.amazon.co.uk/auth/o2/token",
    ads_auth_host="https://eu.account.amazon.com",
    timezone="Europe/Berlin",
)

BY_ID = {m.marketplace_id: m for m in (UK, DE)}
DEFAULT = UK
