import pytest

from packages.shared.amazon_contracts import (
    ADS_REQUIRED_HEADERS,
    SP_REQUIRED_HEADERS,
    ContractEvidence,
    VerificationLevel,
    assert_live_ready_evidence,
    validate_headers,
    validate_method,
    validate_payload,
)
from packages.shared.endpoints import ENDPOINTS, REGIONS, Api


def test_all_catalogued_contracts_use_versioned_absolute_paths_and_known_methods():
    assert ENDPOINTS
    for key, contract in ENDPOINTS.items():
        assert contract.key == key
        assert contract.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert contract.path.startswith("/")
        assert "//" not in contract.path
        assert contract.api in {Api.ADS, Api.SP_API}


def test_eu_hosts_and_uk_marketplace_contract():
    eu = REGIONS["eu"]
    assert eu.ads_host == "https://advertising-api-eu.amazon.com"
    assert eu.sp_host == "https://sellingpartnerapi-eu.amazon.com"
    validate_payload(
        "sp.reports.create",
        {
            "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
            "marketplaceIds": ["A1F83G8C2ARO7P"],
        },
    )
    with pytest.raises(ValueError, match="UK marketplace"):
        validate_payload(
            "sp.reports.create",
            {"reportType": "x", "marketplaceIds": ["ATVPDKIKX0DER"]},
        )


def test_header_contracts_fail_closed():
    with pytest.raises(ValueError, match="required headers"):
        validate_headers("ads.keywords.list", {})
    validate_headers("ads.keywords.list", {key: "x" for key in ADS_REQUIRED_HEADERS})
    with pytest.raises(ValueError, match="required headers"):
        validate_headers("sp.orders.list", {})
    validate_headers("sp.orders.list", {key: "x" for key in SP_REQUIRED_HEADERS})


def test_endpoint_methods_and_mutating_payloads_fail_closed():
    with pytest.raises(ValueError, match="requires POST"):
        validate_method("ads.keywords.list", "GET")
    for key, contract in ENDPOINTS.items():
        validate_method(key, contract.method)
        if contract.mutates:
            with pytest.raises(ValueError, match="non-empty payload"):
                validate_payload(key, {})


def test_ads_report_contract_requires_grain_columns_and_type():
    with pytest.raises(ValueError):
        validate_payload("ads.reports.create", {"name": "x"})
    validate_payload(
        "ads.reports.create",
        {
            "name": "campaign daily",
            "startDate": "2026-09-01",
            "endDate": "2026-09-02",
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": ["campaign"],
                "columns": ["campaignId", "impressions"],
                "reportTypeId": "spCampaigns",
                "timeUnit": "DAILY",
                "format": "GZIP_JSON",
            },
        },
    )


@pytest.mark.parametrize(
    "level",
    [VerificationLevel.STATIC_CONTRACT, VerificationLevel.SANDBOX],
)
def test_non_live_evidence_never_marks_live_ready(level):
    evidence = ContractEvidence(
        "ads.keywords.update", level, "A1F83G8C2ARO7P", "123"
    )
    with pytest.raises(ValueError, match="cannot mark LIVE_READY"):
        assert_live_ready_evidence(evidence)


def test_authorized_ads_evidence_requires_profile_scope():
    without_profile = ContractEvidence(
        "ads.keywords.update",
        VerificationLevel.AUTHORIZED_LIVE_WRITE,
        "A1F83G8C2ARO7P",
    )
    with pytest.raises(ValueError, match="profile"):
        assert_live_ready_evidence(without_profile)
    assert_live_ready_evidence(
        ContractEvidence(
            "ads.keywords.update",
            VerificationLevel.AUTHORIZED_LIVE_WRITE,
            "A1F83G8C2ARO7P",
            "123",
        )
    )
