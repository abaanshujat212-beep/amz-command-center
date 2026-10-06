"""Product research commands with explicit provenance and conservative RBAC."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

EDIT_ROLES = frozenset({"owner", "admin", "user", "analyst"})
MANAGE_ROLES = frozenset({"owner", "admin"})
CANDIDATE_KINDS = frozenset({"own_catalog", "market"})
DISPOSITIONS = frozenset({"new", "watchlist", "shortlisted", "rejected"})
COMPLETENESS = frozenset({"complete", "partial", "blocked"})


@dataclass(frozen=True)
class ResearchRef:
    id: str


def _require(role: str, allowed: frozenset[str]) -> None:
    if role not in allowed:
        raise PermissionError("role cannot modify product research")


def _required(value: str, field: str, limit: int = 300) -> str:
    clean = value.strip()
    if not clean or len(clean) > limit:
        raise ValueError(f"{field} is required and must be at most {limit} characters")
    return clean


def _id(row) -> ResearchRef:
    return ResearchRef(str(row["id"] if isinstance(row, dict) else row[0]))


def create_project(
    conn,
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_role: str,
    name: str,
    objective: str | None = None,
) -> ResearchRef:
    _require(actor_role, EDIT_ROLES)
    row = conn.execute(
        """insert into research_project(tenant_id,name,objective,created_by)
           values(%s,%s,%s,%s) returning id""",
        (tenant_id, _required(name, "project name", 200), objective, actor_user_id),
    ).fetchone()
    return _id(row)


def add_candidate(
    conn,
    *,
    tenant_id: str,
    project_id: str,
    actor_user_id: str,
    actor_role: str,
    candidate_kind: str,
    title: str,
    asin: str | None = None,
    sku: str | None = None,
) -> ResearchRef:
    _require(actor_role, EDIT_ROLES)
    if candidate_kind not in CANDIDATE_KINDS:
        raise ValueError("candidate_kind must be own_catalog or market")
    if candidate_kind == "own_catalog" and not (asin or sku):
        raise ValueError("own_catalog candidates require an ASIN or SKU")
    row = conn.execute(
        """insert into research_candidate(
               tenant_id,project_id,candidate_kind,asin,sku,title,created_by)
           values(%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            project_id,
            candidate_kind,
            asin,
            sku,
            _required(title, "candidate title"),
            actor_user_id,
        ),
    ).fetchone()
    return _id(row)


def add_observation(
    conn,
    *,
    tenant_id: str,
    candidate_id: str,
    actor_role: str,
    metric: str,
    provider: str,
    observed_at: dt.datetime,
    method: str,
    evidence_scope: dict[str, Any],
    completeness: str,
    evidence_ref: str,
    numeric_value: float | None = None,
    text_value: str | None = None,
    unit: str | None = None,
) -> ResearchRef:
    _require(actor_role, EDIT_ROLES)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if completeness not in COMPLETENESS:
        raise ValueError("invalid evidence completeness")
    if (numeric_value is None) == (text_value is None):
        raise ValueError("provide exactly one observation value")
    row = conn.execute(
        """insert into research_observation(
               tenant_id,candidate_id,metric,numeric_value,text_value,unit,provider,
               observed_at,method,evidence_scope,completeness,evidence_ref)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            candidate_id,
            _required(metric, "metric"),
            numeric_value,
            text_value,
            unit,
            _required(provider, "provider"),
            observed_at,
            _required(method, "method"),
            Jsonb(evidence_scope),
            completeness,
            _required(evidence_ref, "evidence_ref", 1000),
        ),
    ).fetchone()
    return _id(row)


def add_assumption(
    conn,
    *,
    tenant_id: str,
    candidate_id: str,
    actor_user_id: str,
    actor_role: str,
    key: str,
    value: Any,
    rationale: str,
) -> ResearchRef:
    _require(actor_role, EDIT_ROLES)
    # Serialize versions per candidate; concurrent writers cannot both select
    # the same next version.
    if (
        conn.execute(
            "select 1 from research_candidate where tenant_id=%s and id=%s for update",
            (tenant_id, candidate_id),
        ).fetchone()
        is None
    ):
        raise LookupError("research candidate not found for tenant")
    row = conn.execute(
        """insert into research_assumption(
               tenant_id,candidate_id,assumption_key,version,value,rationale,created_by)
           select %s,%s,%s,coalesce(max(version),0)+1,%s,%s,%s
             from research_assumption
            where tenant_id=%s and candidate_id=%s and assumption_key=%s
           returning id""",
        (
            tenant_id,
            candidate_id,
            _required(key, "assumption key", 100),
            Jsonb(value),
            _required(rationale, "rationale", 1000),
            actor_user_id,
            tenant_id,
            candidate_id,
            key.strip(),
        ),
    ).fetchone()
    return _id(row)


def set_disposition(
    conn, *, tenant_id: str, candidate_id: str, actor_role: str, status: str
) -> bool:
    _require(actor_role, MANAGE_ROLES)
    if status not in DISPOSITIONS:
        raise ValueError("invalid candidate disposition")
    row = conn.execute(
        """update research_candidate set status=%s,updated_at=now()
            where tenant_id=%s and id=%s returning id""",
        (status, tenant_id, candidate_id),
    ).fetchone()
    return row is not None


def compare_candidates(conn, *, tenant_id: str, candidate_ids: list[str]) -> list[dict]:
    """Return an attributed comparison contract; never calculate market facts."""
    unique_ids = list(dict.fromkeys(candidate_ids))
    if not 2 <= len(unique_ids) <= 10:
        raise ValueError("compare requires 2 to 10 unique candidates")
    return conn.execute(
        """select c.id,c.candidate_kind,c.title,c.asin,c.sku,c.status,
                  coalesce(jsonb_agg(jsonb_build_object(
                    'metric',o.metric,'numeric_value',o.numeric_value,
                    'text_value',o.text_value,'unit',o.unit,'provider',o.provider,
                    'observed_at',o.observed_at,'method',o.method,
                    'scope',o.evidence_scope,'completeness',o.completeness,
                    'evidence_ref',o.evidence_ref
                  ) order by o.observed_at desc) filter(where o.id is not null),'[]') as evidence
             from research_candidate c
             left join research_observation o
               on o.tenant_id=c.tenant_id and o.candidate_id=c.id
            where c.tenant_id=%s and c.id=any(%s)
            group by c.id order by c.title""",
        (tenant_id, unique_ids),
    ).fetchall()
