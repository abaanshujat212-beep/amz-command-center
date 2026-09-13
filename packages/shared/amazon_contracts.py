"""Executable Amazon request-contract gates.

Static verification proves only that code matches the reviewed contract. It must
never be interpreted as authorized production evidence or LIVE_READY status.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from packages.shared.endpoints import Api, Endpoint, endpoint

UK_MARKETPLACE_ID = "A1F83G8C2ARO7P"
ADS_REQUIRED_HEADERS = frozenset({"Amazon-Advertising-API-ClientId", "Authorization", "Amazon-Advertising-API-Scope"})
SP_REQUIRED_HEADERS = frozenset({"Authorization", "x-amz-access-token"})


class VerificationLevel(StrEnum):
    STATIC_CONTRACT = "STATIC_CONTRACT"
    SANDBOX = "SANDBOX"
    AUTHORIZED_LIVE_READ = "AUTHORIZED_LIVE_READ"
    AUTHORIZED_LIVE_WRITE = "AUTHORIZED_LIVE_WRITE"


@dataclass(frozen=True)
class ContractEvidence:
    endpoint_key: str
    level: VerificationLevel
    marketplace_id: str
    profile_id: str | None = None

    @property
    def production_evidence(self) -> bool:
        return self.level in {VerificationLevel.AUTHORIZED_LIVE_READ, VerificationLevel.AUTHORIZED_LIVE_WRITE}


def validate_headers(endpoint_key: str, headers: dict[str, str]) -> None:
    ep = endpoint(endpoint_key)
    required = ADS_REQUIRED_HEADERS if ep.api is Api.ADS else SP_REQUIRED_HEADERS
    missing = sorted(required - headers.keys())
    if missing:
        raise ValueError(f"{endpoint_key} missing required headers: {missing}")
    if ep.api is Api.ADS and not headers["Amazon-Advertising-API-Scope"].strip():
        raise ValueError("Ads profile scope must not be empty")


def validate_method(endpoint_key: str, method: str) -> Endpoint:
    ep = endpoint(endpoint_key)
    if method.upper() != ep.method:
        raise ValueError(f"{endpoint_key} requires {ep.method}, got {method.upper()}")
    return ep


def validate_payload(endpoint_key: str, payload: dict[str, Any] | None) -> None:
    payload = payload or {}
    if endpoint_key == "ads.reports.create":
        required = {"name", "startDate", "endDate", "configuration"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"missing Ads report fields: {sorted(missing)}")
        config = payload["configuration"]
        for key in ("adProduct", "groupBy", "columns", "reportTypeId", "timeUnit", "format"):
            if key not in config:
                raise ValueError(f"missing Ads report configuration.{key}")
        if not config["groupBy"] or not config["columns"]:
            raise ValueError("Ads report groupBy and columns must not be empty")
    elif endpoint_key == "sp.reports.create":
        if not payload.get("reportType") or not payload.get("marketplaceIds"):
            raise ValueError("SP report requires reportType and marketplaceIds")
        if UK_MARKETPLACE_ID not in payload["marketplaceIds"]:
            raise ValueError("UK deployment requires the UK marketplace id")
    elif endpoint(endpoint_key).mutates and not payload:
        raise ValueError(f"mutating endpoint {endpoint_key} requires a non-empty payload")


def assert_live_ready_evidence(evidence: ContractEvidence) -> None:
    if not evidence.production_evidence:
        raise ValueError("fixture, documentation and sandbox evidence cannot mark LIVE_READY")
    ep = endpoint(evidence.endpoint_key)
    if ep.api is Api.ADS and not evidence.profile_id:
        raise ValueError("Ads live evidence must identify the advertiser profile")
