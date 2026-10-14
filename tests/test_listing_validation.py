import pytest

from services.listings.validation import Draft, Fact, prompt_fingerprint, validate_draft


def fact(**overrides):
    values = {"id": "f1", "tenant_id": "tenant-a", "key": "material", "value": "steel", "source_type": "manual", "source_ref": "operator:1"}
    values.update(overrides)
    return Fact(**values)


def draft(**overrides):
    values = {"title": "Stainless steel bottle", "bullets": ("Reusable bottle",), "description": "Made from steel.", "backend_terms": ("steel bottle",)}
    values.update(overrides)
    return Draft(**values)


def validate(value=None, **overrides):
    values = {"tenant_id": "tenant-a", "facts": [fact()], "cited_fact_ids": ["f1"], "keyword_bank": ["steel bottle"], "product_type": "WATER_BOTTLE", "ptd_contract_verified": True, "restrictions_status": "clear"}
    values.update(overrides)
    return validate_draft(value or draft(), **values)


def test_valid_grounded_draft_can_advance():
    assert validate().can_advance


@pytest.mark.parametrize("copy", ["Guaranteed results", "The best bottle", "Cures a disease"])
def test_prohibited_claims_fail_closed(copy):
    result = validate(draft(title=copy))
    assert not result.can_advance
    assert any(issue.field == "title" for issue in result.issues)


def test_ptd_and_restrictions_are_required_not_assumed():
    result = validate(ptd_contract_verified=False, restrictions_status="unknown")
    assert {issue.code for issue in result.issues} >= {"ptd_unverified", "restrictions_not_clear"}


def test_cross_tenant_unknown_and_competitor_sources_fail_closed():
    result = validate(facts=[fact(tenant_id="tenant-b", source_type="competitor")], cited_fact_ids=["missing"])
    assert {issue.code for issue in result.issues} >= {"cross_tenant_source", "competitor_source", "unknown_source"}


def test_backend_terms_must_use_keyword_bank_and_byte_limit():
    result = validate(draft(backend_terms=("unapproved", "é" * 125)))
    assert {issue.code for issue in result.issues} >= {"keyword_not_approved", "backend_terms_too_long"}


def test_prompt_fingerprint_is_deterministic_and_contains_no_source_copy():
    first = prompt_fingerprint(template_version="listing-v1", fact_ids=["b", "a"], keywords=["steel"])
    second = prompt_fingerprint(template_version="listing-v1", fact_ids=["a", "b"], keywords=["steel"])
    assert first == second and len(first) == 64
    assert "steel" not in first
