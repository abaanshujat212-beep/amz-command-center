import json
from dataclasses import replace

import pytest

from services.listings.title_preview_fixture import (
    DraftSnapshot,
    LocalValidation,
    Scope,
    prepare_title_fixture,
    run_title_fixture,
)
from services.listings.validation import Draft

SCOPE = Scope("tenant", "project", "connection", "seller", "marketplace", "SKU-001")
DRAFT = DraftSnapshot(SCOPE, "draft-2", Draft("New title", ("Draft bullet",), "Copy", ()))
VALIDATION = LocalValidation(SCOPE, "draft-2", "validation-5", "PRODUCT", True)
BASELINE = {
    "item_name": [{"marketplace_id":"marketplace", "language_tag":"en_GB", "value":"Old title"}],
    "bullet_point": [{"value":"Existing seller bullet"}],
    "main_product_image_locator": [{"media_location":"https://example.test/image"}],
}


def context(**overrides):
    return {
        "draft": DRAFT, "validation": VALIDATION, "latest_draft_id": "draft-2",
        "baseline_scope": SCOPE, "baseline_product_type": "PRODUCT", "attributes": BASELINE,
        "expected_language_tag":"en_GB", "schema_version":"opaque-example-version", "schema_fixture_sha256":"a"*64,
    } | overrides


def prepare(**overrides):
    return prepare_title_fixture(**context(**overrides))


def test_fixture_requests_exactly_one_existing_title_patch_and_fixed_preview_mode():
    request, binding = prepare()
    assert request["operation"] == "patchListingsItem"
    assert request["query"] == {"marketplaceIds":["marketplace"], "mode":"VALIDATION_PREVIEW"}
    assert request["body"] == {"productType":"PRODUCT", "patches":[
        {"op":"replace", "path":"/attributes/item_name", "value":[
            {"marketplace_id":"marketplace", "language_tag":"en_GB", "value":"New title"},
        ]},
    ]}
    assert BASELINE["item_name"][0]["value"] == "Old title"
    assert "bullet" not in json.dumps(request) and "image" not in json.dumps(request)
    assert len(binding) == 64


@pytest.mark.parametrize("modification", [
    {"latest_draft_id":"draft-3"},
    {"baseline_scope": replace(SCOPE, tenant_id="other")},
    {"baseline_scope": replace(SCOPE, seller_connection_id="other")},
    {"baseline_scope": replace(SCOPE, marketplace_id="other")},
    {"baseline_scope": replace(SCOPE, sku="other")},
    {"validation": replace(VALIDATION, draft_id="old")},
    {"validation": replace(VALIDATION, passed=False)},
    {"baseline_product_type":"OTHER"},
    {"schema_fixture_sha256":"not-evidence"},
    {"attributes":{}},
    {"expected_language_tag":"de_DE"},
    {"draft":replace(DRAFT, content=replace(DRAFT.content, title=" "))},
    {"attributes":{"item_name":BASELINE["item_name"]*2}},
])
def test_scope_or_evidence_mismatch_blocks_fixture(modification):
    with pytest.raises(ValueError):
        prepare(**modification)


def test_baseline_schema_exact_draft_and_local_evidence_changes_invalidate_hash():
    old = prepare()[1]
    for options in [
        {"attributes":BASELINE | {"bullet_point":[{"value":"Baseline changed"}]}},
        {"schema_fixture_sha256":"b"*64}, {"schema_version":"43"},
        {"validation":replace(VALIDATION, validation_id="validation-6")},
        {"draft":replace(DRAFT, content=replace(DRAFT.content, title="Different title"))},
        {"draft":replace(DRAFT, content=replace(DRAFT.content, bullets=("Changed draft bullet",)))},
    ]:
        assert prepare(**options)[1] != old


def test_unknown_issue_code_is_retained_without_prose_and_never_certifies_live_status():
    _, evidence = run_title_fixture({
        "sku":SCOPE.sku, "status":"INVALID",
        "issues":[{"code":"NEW_ISSUE_123", "severity":"ERROR", "message":"fixture text"}],
    }, **context())
    assert evidence.source == "offline_fixture"
    assert evidence.outcome == "INVALID" and evidence.issues == (("NEW_ISSUE_123", "ERROR"),)
    assert "fixture text" not in repr(evidence)


@pytest.mark.parametrize("response", [
    {"status":"ACCEPTED", "issues":[]},
    {"status":"VALID", "issues":[{"code":"SAFE", "severity":"UNKNOWN"}]},
    {"status":"VALID", "issues":[{"code":"SAFE", "severity":"ERROR"}]},
    {"status":"VALID", "issues":[{"code":"invalid code with spaces", "severity":"WARNING"}]},
    {"status":"VALID"},
])
def test_live_acceptance_malformed_or_conflicting_fixture_response_is_not_evidence(response):
    with pytest.raises(ValueError):
        run_title_fixture({"sku": SCOPE.sku, **response}, **context())



def test_response_sku_and_caller_mode_override_fail_closed():
    response = {"sku": SCOPE.sku, "status": "VALID", "issues": []}
    request, evidence = run_title_fixture(response, **context())
    assert request["query"]["mode"] == "VALIDATION_PREVIEW"
    assert evidence.outcome == "VALID"
    assert evidence.binding_sha256 == prepare()[1]
    with pytest.raises(ValueError):
        run_title_fixture(response | {"sku": "OTHER"}, **context())
    with pytest.raises(TypeError):
        run_title_fixture(response, **context(mode="LIVE"))
