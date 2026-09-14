"""Tenant-scoped Party repository; callers own transactions and RBAC context."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@dataclass(frozen=True)
class PartyInput:
    display_name: str
    party_kind: str = "organization"
    legal_name: str | None = None


def create_party(conn, tenant_id: str, value: PartyInput) -> dict:
    row = conn.execute(
        """insert into party (tenant_id,party_kind,display_name,legal_name,normalized_name)
           values (%s,%s,%s,%s,%s) returning *""",
        (tenant_id, value.party_kind, value.display_name, value.legal_name, normalize(value.display_name)),
    ).fetchone()
    return dict(row)


def search_parties(conn, tenant_id: str, query: str, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        """select p.*, coalesce(array_agg(pr.role_type) filter (where pr.role_type is not null), '{}') roles
             from party p left join party_role pr on pr.tenant_id=p.tenant_id and pr.party_id=p.id
            where p.tenant_id=%s and p.status='active' and p.normalized_name like %s
            group by p.id order by p.normalized_name limit %s""",
        (tenant_id, f"%{normalize(query)}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def add_role(conn, tenant_id: str, party_id: str, role_type: str) -> None:
    conn.execute(
        "insert into party_role(tenant_id,party_id,role_type) values(%s,%s,%s) on conflict do nothing",
        (tenant_id, party_id, role_type),
    )


def merge_party(conn, tenant_id: str, source_id: str, target_id: str, actor_user_id: str | None = None) -> None:
    if source_id == target_id:
        raise ValueError("cannot merge a party into itself")
    source, target = uuid.UUID(source_id), uuid.UUID(target_id)
    locked = conn.execute(
        "select id from party where tenant_id=%s and id=any(%s) and status='active' for update",
        (tenant_id, [source, target]),
    ).fetchall()
    if len(locked) != 2:
        raise ValueError("both active parties must exist in the tenant")
    conn.execute(
        """insert into party_role(tenant_id,party_id,role_type,extension)
           select tenant_id,%s,role_type,extension from party_role where tenant_id=%s and party_id=%s
           on conflict do nothing""",
        (target, tenant_id, source),
    )
    conn.execute("update contact set party_id=%s where tenant_id=%s and party_id=%s", (target, tenant_id, source))
    conn.execute("update party_address set party_id=%s where tenant_id=%s and party_id=%s", (target, tenant_id, source))
    conn.execute(
        "update party set status='merged',merged_into_party_id=%s,updated_at=now() where tenant_id=%s and id=%s",
        (target, tenant_id, source),
    )
    conn.execute(
        "insert into party_merge_history(tenant_id,source_party_id,target_party_id,actor_user_id) values(%s,%s,%s,%s)",
        (tenant_id, source, target, actor_user_id),
    )
