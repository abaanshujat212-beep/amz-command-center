"""Offline-only contract fixture; never accepts a transport or produces live approval evidence."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

from services.listings.validation import Draft

_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}", re.ASCII)
_SHA = re.compile(r"[a-f0-9]{64}", re.ASCII)


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    project_id: str
    seller_connection_id: str
    seller_id: str
    marketplace_id: str
    sku: str


@dataclass(frozen=True)
class DraftSnapshot:
    scope: Scope
    draft_id: str
    content: Draft


@dataclass(frozen=True)
class LocalValidation:
    """Projection of existing local evidence, not provider validation."""
    scope: Scope
    draft_id: str
    validation_id: str
    product_type: str
    passed: bool


@dataclass(frozen=True)
class FixtureEvidence:
    binding_sha256: str
    outcome: Literal["VALID", "INVALID"]
    issues: tuple[tuple[str, str], ...]
    source: Literal["offline_fixture"] = "offline_fixture"


def _fingerprint(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def prepare_title_fixture(
    draft: DraftSnapshot, validation: LocalValidation, *, latest_draft_id: str,
    baseline_scope: Scope, baseline_product_type: str, attributes: dict,
    schema_version: str, schema_fixture_sha256: str, expected_language_tag: str,
) -> tuple[dict, str]:
    """Build fixture data; schema_fixture_sha256 is supplied local metadata, not Amazon proof."""
    scope = draft.scope
    if (
        not all(isinstance(v, str) and v.strip() for v in asdict(scope).values())
        or draft.scope != baseline_scope or validation.scope != scope
        or not draft.draft_id or draft.draft_id != latest_draft_id
        or validation.draft_id != draft.draft_id or not validation.validation_id
        or validation.passed is not True
    ):
        raise ValueError("Current draft, validation and SKU fixture must share an exact scope")
    if not (
        baseline_product_type and validation.product_type == baseline_product_type
        and schema_version and _SHA.fullmatch(schema_fixture_sha256)
    ):
        raise ValueError("An exact fixture product type and schema version/checksum are required")
    title = draft.content.title.strip()
    ordinal = attributes.get("item_name")
    if (
        not title or len(title) > 200 or not isinstance(ordinal, list) or len(ordinal) != 1
        or not isinstance(ordinal[0], dict)
    ):
        raise ValueError("A single existing title attribute and a valid replacement are required")
    old = ordinal[0]
    if (
        set(old) != {"value", "marketplace_id", "language_tag"}
        or old["marketplace_id"] != scope.marketplace_id
        or not isinstance(old["value"], str) or not old["value"].strip()
        or not expected_language_tag.strip() or old["language_tag"] != expected_language_tag
        or old["value"].strip() == title
    ):
        raise ValueError("Title selectors are unavailable, ambiguous, or unchanged")
    request = {
        "operation": "patchListingsItem",
        "query": {"marketplaceIds": [scope.marketplace_id], "mode": "VALIDATION_PREVIEW"},
        "body": {
            "productType": baseline_product_type,
            "patches": [{"op": "replace", "path": "/attributes/item_name",
                         "value": [{**old, "value": title}]}],
        },
    }
    binding = _fingerprint({
        "scope": asdict(scope), "draft": asdict(draft), "validation": asdict(validation),
        "attributes": attributes, "schema_version": schema_version,
        "schema_fixture_sha256": schema_fixture_sha256, "request": request,
    })
    return request, binding


def _evaluate_fixture_response(
    response: dict, *, binding_sha256: str, expected_sku: str,
) -> FixtureEvidence:
    """Reduce synthetic results, including unknown issue codes, without raw provider prose."""
    outcome = response.get("status")
    raw = response.get("issues")
    if response.get("sku") != expected_sku or outcome not in ("VALID", "INVALID"):
        raise ValueError("Not a Validation Preview fixture outcome")
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Malformed fixture issues")
    issues = []
    for issue in raw:
        if not isinstance(issue, dict):
            raise ValueError("Malformed fixture issue")
        code, severity = issue.get("code"), issue.get("severity")
        if not isinstance(code, str) or not _CODE.fullmatch(code) or severity not in (
            "ERROR", "WARNING", "INFO",
        ):
            raise ValueError("Malformed fixture issue code or severity")
        issues.append((code, severity))
    if outcome == "VALID" and any(severity == "ERROR" for _, severity in issues):
        raise ValueError("Conflicting Validation Preview fixture response")
    return FixtureEvidence(binding_sha256, outcome, tuple(issues))


def run_title_fixture(
    response: dict, draft: DraftSnapshot, validation: LocalValidation, **fixture_context,
) -> tuple[dict, FixtureEvidence]:
    """Build the fixed request and normalize its synthetic paired response.

    The binding proves correspondence to the supplied fixture inputs only;
    it is not provider authenticity and cannot authorize review or submission.
    """
    request, binding = prepare_title_fixture(draft, validation, **fixture_context)
    return request, _evaluate_fixture_response(
        response, binding_sha256=binding, expected_sku=draft.scope.sku,
    )
