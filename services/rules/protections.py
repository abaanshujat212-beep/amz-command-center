"""Tenant protection policy evaluated before automated proposals are queued."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

DESTRUCTIVE_ACTIONS = frozenset(
    {
        "add_negative_exact",
        "add_negative_phrase",
        "pause",
        "set_status_paused",
    }
)


@dataclass(frozen=True)
class ProtectionDecision:
    blocked: bool
    protection_id: str | None = None
    policy: str | None = None
    reason: str | None = None


def active_protection(
    conn,
    *,
    tenant_id: str,
    entity_type: str,
    entity_value: str,
    product_scope: str = "*",
    action_type: str,
    now: dt.datetime | None = None,
) -> ProtectionDecision:
    """Return a fail-closed decision for a destructive automated action."""
    if action_type not in DESTRUCTIVE_ACTIONS:
        return ProtectionDecision(False)
    instant = now or dt.datetime.now(dt.timezone.utc)
    row = conn.execute(
        """select p.id,p.policy,p.reason,p.duration,p.expires_at,
                  (select e.event_type from entity_protection_event e
                    where e.tenant_id=p.tenant_id and e.protection_id=p.id
                    order by e.occurred_at desc,e.id desc limit 1) latest_event
             from entity_protection p
            where p.tenant_id=%s and p.entity_type=%s
              and lower(p.entity_value)=lower(%s)
              and p.product_scope in ('*',%s)
              and (p.expires_at is null or p.expires_at>%s)
            order by (p.product_scope=%s) desc,p.created_at desc,p.id desc limit 1""",
        (tenant_id, entity_type, entity_value.strip(), product_scope, instant, product_scope),
    ).fetchone()
    if row is None or row["latest_event"] in {"released", "consumed"}:
        return ProtectionDecision(False)
    # allow/protect both prevent destructive automation. deny is an explicit
    # instruction to exclude and therefore does not block a matching negative.
    blocked = row["policy"] in {"allow", "protect"}
    return ProtectionDecision(blocked, str(row["id"]), row["policy"], row["reason"])


def consume_one_time(conn, *, tenant_id: str, protection_id: str, actor_user_id: str) -> None:
    row = conn.execute(
        "select duration from entity_protection where tenant_id=%s and id=%s",
        (tenant_id, protection_id),
    ).fetchone()
    if row and row["duration"] == "one_time":
        conn.execute(
            """insert into entity_protection_event(
                 tenant_id,protection_id,event_type,reason,actor_user_id)
               values(%s,%s,'consumed','one-time protection consumed',%s)""",
            (tenant_id, protection_id, actor_user_id),
        )
