"""Fail-closed resolver for human override and automation-lock ownership."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlDecision:
    blocked: bool
    state: str = "AUTOMATED"
    control_id: str | None = None
    reason: str | None = None


def active_control(
    conn,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    product_scope: str = "*",
    action_control_id: str | None = None,
    now: dt.datetime | None = None,
) -> ControlDecision:
    """Return ownership state; only an action linked to that control may proceed."""
    instant = now or dt.datetime.now(dt.timezone.utc)
    result = conn.execute(
        """select c.id,c.duration,c.expires_at,c.reason,(select e.state from entity_automation_control_event e
              where e.tenant_id=c.tenant_id and e.control_id=c.id order by e.occurred_at desc,e.id desc limit 1) state
             from entity_automation_control c where c.tenant_id=%s and c.entity_type=%s and lower(c.entity_id)=lower(%s)
              and c.product_scope in ('*',%s) order by (c.product_scope=%s) desc,c.created_at desc,c.id desc limit 1""",
        (tenant_id, entity_type, entity_id.strip(), product_scope, product_scope),
    )
    # Lightweight worker fakes created before this safety layer may not model
    # unrelated SELECTs; production psycopg always returns a cursor here.
    row = result.fetchone() if result is not None else None
    if row is None or row["state"] == "AUTOMATED":
        return ControlDecision(False)
    control_id = str(row["id"])
    if action_control_id == control_id:
        return ControlDecision(False, row["state"], control_id, row["reason"])
    state = (
        "REVIEW_DUE"
        if row["duration"] == "temporary" and row["expires_at"] <= instant
        else row["state"]
    )
    return ControlDecision(True, state, control_id, row["reason"])


def complete_one_time_control(conn, *, tenant_id: str, control_id: str | None) -> None:
    """Return a one-time override to automation after its linked action succeeds."""
    if not control_id:
        return
    row = conn.execute(
        "select duration,created_by from entity_automation_control where tenant_id=%s and id=%s",
        (tenant_id, control_id),
    ).fetchone()
    if row and row["duration"] == "one_time":
        conn.execute(
            """insert into entity_automation_control_event(tenant_id,control_id,state,reason,actor_user_id)
               values(%s,%s,'AUTOMATED','one-time human action completed',%s)""",
            (tenant_id, control_id, row["created_by"]),
        )
