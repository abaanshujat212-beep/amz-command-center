"""Listing Studio commands with immutable versions and review-state guards."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg.types.json import Jsonb

EDIT_ROLES = frozenset({"owner", "admin", "user", "analyst"})
REVIEW_ROLES = frozenset({"owner", "admin"})


@dataclass(frozen=True)
class ListingRef:
    id: str
    version: int | None = None


def _require(role: str, allowed: frozenset[str]) -> None:
    if role not in allowed:
        raise PermissionError("role cannot perform this listing operation")


def _required(value: str, name: str, limit: int) -> str:
    clean = value.strip()
    if not clean or len(clean) > limit:
        raise ValueError(f"{name} is required and must be at most {limit} characters")
    return clean


def _cell(row, name: str, index: int = 0):
    return row[name] if isinstance(row, dict) else row[index]


def create_project(
    conn,
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_role: str,
    name: str,
    asin: str | None = None,
    sku: str | None = None,
    research_candidate_id: str | None = None,
) -> ListingRef:
    _require(actor_role, EDIT_ROLES)
    row = conn.execute(
        """insert into listing_project(
               tenant_id,research_candidate_id,name,asin,sku,created_by)
           values(%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            research_candidate_id,
            _required(name, "project name", 200),
            asin,
            sku,
            actor_user_id,
        ),
    ).fetchone()
    return ListingRef(str(_cell(row, "id")))


def create_draft_version(
    conn,
    *,
    tenant_id: str,
    project_id: str,
    actor_user_id: str,
    actor_role: str,
    title: str,
    bullets: list[str],
    description: str,
    backend_terms: list[str],
    product_fact_ids: list[str],
    change_summary: str,
    keyword_plan_version_id: str | None = None,
    origin: str = "human",
    generation_ref: str | None = None,
) -> ListingRef:
    _require(actor_role, EDIT_ROLES)
    if origin not in {"human", "ai_assisted", "imported"}:
        raise ValueError("invalid draft origin")
    if origin == "ai_assisted" and not generation_ref:
        raise ValueError("AI-assisted drafts require generation provenance")
    if len(title) > 500 or len(bullets) > 10 or any(len(item) > 1000 for item in bullets):
        raise ValueError("listing content exceeds safe limits")
    project = conn.execute(
        "select review_state from listing_project where tenant_id=%s and id=%s for update",
        (tenant_id, project_id),
    ).fetchone()
    if project is None:
        raise LookupError("listing project not found for tenant")
    if _cell(project, "review_state") == "archived":
        raise ValueError("archived listing projects cannot be edited")
    previous = conn.execute(
        """select id,version from listing_draft_version
            where tenant_id=%s and project_id=%s order by version desc limit 1""",
        (tenant_id, project_id),
    ).fetchone()
    version = int(_cell(previous, "version", 1)) + 1 if previous else 1
    previous_id = _cell(previous, "id") if previous else None
    row = conn.execute(
        """insert into listing_draft_version(
               tenant_id,project_id,version,previous_version_id,title,bullets,
               description,backend_terms,keyword_plan_version_id,
               origin,generation_ref,change_summary,created_by)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            project_id,
            version,
            previous_id,
            title,
            Jsonb(bullets),
            description,
            Jsonb(backend_terms),
            keyword_plan_version_id,
            origin,
            generation_ref,
            _required(change_summary, "change summary", 1000),
            actor_user_id,
        ),
    ).fetchone()
    draft_id = str(_cell(row, "id"))
    for fact_id in dict.fromkeys(product_fact_ids):
        conn.execute(
            """insert into listing_draft_fact(tenant_id,draft_version_id,product_fact_id)
               values(%s,%s,%s)""",
            (tenant_id, draft_id, fact_id),
        )
    conn.execute(
        "update listing_project set review_state='draft',updated_at=now() where tenant_id=%s and id=%s",
        (tenant_id, project_id),
    )
    return ListingRef(draft_id, version)


def review_draft(
    conn,
    *,
    tenant_id: str,
    project_id: str,
    draft_version_id: str,
    actor_user_id: str,
    actor_role: str,
    decision: str,
    comment: str | None = None,
) -> None:
    allowed = {
        "submitted": (EDIT_ROLES, "in_review"),
        "approved": (REVIEW_ROLES, "approved"),
        "changes_requested": (REVIEW_ROLES, "changes_requested"),
        "returned_to_draft": (REVIEW_ROLES, "draft"),
    }
    if decision not in allowed:
        raise ValueError("invalid listing review decision")
    roles, target = allowed[decision]
    _require(actor_role, roles)
    latest = conn.execute(
        """select id from listing_draft_version where tenant_id=%s and project_id=%s
            order by version desc limit 1 for update""",
        (tenant_id, project_id),
    ).fetchone()
    if latest is None or str(_cell(latest, "id")) != str(draft_version_id):
        raise ValueError("only the latest draft version can enter review")
    conn.execute(
        """insert into listing_review_event(
               tenant_id,project_id,draft_version_id,decision,comment,actor_user_id)
           values(%s,%s,%s,%s,%s,%s)""",
        (tenant_id, project_id, draft_version_id, decision, comment, actor_user_id),
    )
    conn.execute(
        "update listing_project set review_state=%s,updated_at=now() where tenant_id=%s and id=%s",
        (target, tenant_id, project_id),
    )
