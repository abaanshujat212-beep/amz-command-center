"""Deterministic safety checks for AI-assisted Amazon listing drafts.

The model may propose copy; this module alone decides whether it can advance.
No function in this module calls Amazon or accepts competitor copy as evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

PROHIBITED_CLAIMS = (
    ("guarantee", re.compile(r"\b(?:guaranteed?|100% guaranteed)\b", re.I)),
    ("unverified_superlative", re.compile(r"(?:\b#\s*1\b|\bbest\b|\bnumber one\b)", re.I)),
    ("medical_claim", re.compile(r"\b(?:cures?|treats?|prevents?)\s+(?:a|an|the)?\s*(?:disease|illness|condition|infection)\b", re.I)),
)
COMPETITOR_MARKERS = frozenset({"competitor", "competitor_listing", "retailer_copy"})


@dataclass(frozen=True)
class Fact:
    id: str
    tenant_id: str
    key: str
    value: object
    source_type: str
    source_ref: str


@dataclass(frozen=True)
class Draft:
    title: str
    bullets: tuple[str, ...]
    description: str
    backend_terms: tuple[str, ...]


@dataclass(frozen=True)
class Issue:
    code: str
    field: str
    severity: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[Issue, ...]

    @property
    def can_advance(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def prompt_fingerprint(*, template_version: str, fact_ids: list[str], keywords: list[str]) -> str:
    """Record reproducible prompt inputs without persisting tenant prose."""
    payload = json.dumps(
        {"template": template_version, "facts": sorted(set(fact_ids)), "keywords": keywords},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_grounding(*, tenant_id: str, facts: list[Fact], cited_fact_ids: list[str]) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    fact_by_id = {fact.id: fact for fact in facts}
    if any(fact.tenant_id != tenant_id for fact in facts):
        issues.append(Issue("cross_tenant_source", "sources", "error", "A source belongs to another tenant."))
    if any(fact.source_type.lower() in COMPETITOR_MARKERS for fact in facts):
        issues.append(Issue("competitor_source", "sources", "error", "Competitor copy cannot be used as listing evidence."))
    unknown = sorted(set(cited_fact_ids).difference(fact_by_id))
    if unknown:
        issues.append(Issue("unknown_source", "sources", "error", "The draft cites an unavailable product fact."))
    if not cited_fact_ids:
        issues.append(Issue("ungrounded_draft", "sources", "error", "At least one tenant product fact must support the draft."))
    return tuple(issues)


def validate_draft(
    draft: Draft,
    *,
    tenant_id: str,
    facts: list[Fact],
    cited_fact_ids: list[str],
    keyword_bank: list[str],
    product_type: str | None,
    ptd_contract_verified: bool,
    restrictions_status: str,
) -> ValidationResult:
    issues = list(validate_grounding(tenant_id=tenant_id, facts=facts, cited_fact_ids=cited_fact_ids))
    if not product_type or not ptd_contract_verified:
        issues.append(Issue("ptd_unverified", "product_type", "error", "A verified Amazon product-type contract is required before review."))
    if restrictions_status != "clear":
        issues.append(Issue("restrictions_not_clear", "restrictions", "error", "Amazon restrictions must be verified clear before review."))

    fields = [("title", draft.title), ("description", draft.description)] + [
        (f"bullet_{index + 1}", value) for index, value in enumerate(draft.bullets)
    ]
    for field, value in fields:
        for code, pattern in PROHIBITED_CLAIMS:
            if pattern.search(value):
                issues.append(Issue(code, field, "error", "Remove prohibited or unverifiable claims."))
    if len(draft.title) > 200:
        issues.append(Issue("title_too_long", "title", "error", "Title exceeds the conservative 200-character limit."))
    if len(draft.bullets) > 5:
        issues.append(Issue("too_many_bullets", "bullets", "error", "Use no more than five bullets."))
    for index, bullet in enumerate(draft.bullets):
        if len(bullet) > 500:
            issues.append(Issue("bullet_too_long", f"bullet_{index + 1}", "error", "Bullet exceeds 500 characters."))
    if len(" ".join(draft.backend_terms).encode("utf-8")) > 249:
        issues.append(Issue("backend_terms_too_long", "backend_terms", "error", "Backend terms exceed 249 UTF-8 bytes."))

    allowed_keywords = {keyword.casefold().strip() for keyword in keyword_bank if keyword.strip()}
    unknown_terms = [term for term in draft.backend_terms if term.casefold().strip() not in allowed_keywords]
    if unknown_terms:
        issues.append(Issue("keyword_not_approved", "backend_terms", "error", "Backend terms must come from the approved keyword bank."))
    return ValidationResult(tuple(issues))
