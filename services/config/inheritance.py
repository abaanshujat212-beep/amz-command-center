"""Versioned configuration mutations and deterministic effective-value tracing."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Mapping

from psycopg.types.json import Jsonb

SCOPE_PRECEDENCE = ("tenant", "marketplace", "entity")
HARD_CAPS = {
    "max_bid": "absolute_max_bid",
    "max_daily_budget": "absolute_max_daily_budget",
    "max_changes_per_day": "absolute_max_changes_per_day",
}


@dataclass(frozen=True)
class ConfigSource:
    level: str
    source_id: str
    version: int
    hard_guard: bool = False


@dataclass(frozen=True)
class EffectiveConfiguration:
    values: Mapping[str, object]
    sources: Mapping[str, ConfigSource]
    resolved_at: dt.datetime


def _value(row, key, index):
    return row[key] if isinstance(row, dict) else row[index]


def _validate_scopes(tenant_id: str, scopes: Mapping[str, str]) -> dict[str, str]:
    unknown = set(scopes).difference(SCOPE_PRECEDENCE)
    if unknown:
        raise ValueError(f"unsupported configuration scope(s): {', '.join(sorted(unknown))}")
    normalized = {key: str(value).strip() for key, value in scopes.items()}
    if normalized.get("tenant") != str(tenant_id):
        raise ValueError("tenant scope must equal tenant_id")
    if any(not value for value in normalized.values()):
        raise ValueError("configuration scope ids cannot be blank")
    return normalized


def resolve_effective_configuration(
    conn,
    *,
    tenant_id: str,
    scopes: Mapping[str, str],
    at: dt.datetime | None = None,
) -> EffectiveConfiguration:
    """Merge active definitions and latest attached overrides with provenance."""
    normalized = _validate_scopes(tenant_id, scopes)
    resolved_at = at or dt.datetime.now(dt.timezone.utc)
    definitions = conn.execute(
        """select distinct on (key) key,version,default_value,hard_guard
             from configuration_definition_version
            where effective_from <= %s and (effective_to is null or effective_to > %s)
            order by key,version desc""",
        (resolved_at, resolved_at),
    ).fetchall()
    values: dict[str, object] = {}
    sources: dict[str, ConfigSource] = {}
    hard_guards: set[str] = set()
    for row in definitions:
        key = _value(row, "key", 0)
        values[key] = _value(row, "default_value", 2)
        is_hard = _value(row, "hard_guard", 3)
        sources[key] = ConfigSource("system", key, _value(row, "version", 1), is_hard)
        if is_hard:
            hard_guards.add(key)

    rows = conn.execute(
        """select distinct on (scope_type,scope_id)
                  id,scope_type,scope_id,version,operation,values
             from configuration_override_version
            where tenant_id=%s and scope_type=any(%s) and scope_id=any(%s)
            order by scope_type,scope_id,version desc""",
        (tenant_id, list(normalized), list(normalized.values())),
    ).fetchall()
    active = {
        _value(row, "scope_type", 1): row
        for row in rows
        if normalized.get(_value(row, "scope_type", 1)) == _value(row, "scope_id", 2)
    }
    for scope_type in SCOPE_PRECEDENCE:
        row = active.get(scope_type)
        if row is None or _value(row, "operation", 4) == "detach":
            continue
        override_values = _value(row, "values", 5)
        for key, value in override_values.items():
            if key in hard_guards:
                raise RuntimeError(f"stored override attempts to replace hard guard: {key}")
            if key not in values:
                raise RuntimeError(f"stored override contains unknown key: {key}")
            values[key] = value
            sources[key] = ConfigSource(
                scope_type,
                _value(row, "scope_id", 2),
                _value(row, "version", 3),
            )

    for local_key, cap_key in HARD_CAPS.items():
        if local_key in values and cap_key in values and values[local_key] > values[cap_key]:
            values[local_key] = values[cap_key]
            sources[local_key] = sources[cap_key]
    if values.get("min_bid", 0) > values.get("max_bid", float("inf")):
        raise RuntimeError("effective min_bid exceeds max_bid")
    return EffectiveConfiguration(values, sources, resolved_at)


def diff_configuration(current: EffectiveConfiguration, proposed: Mapping[str, object]) -> dict:
    """Return only changed keys, retaining the current source trace."""
    return {
        key: {"before": current.values.get(key), "after": value, "source": current.sources.get(key)}
        for key, value in proposed.items()
        if current.values.get(key) != value
    }


def _require_admin(conn, tenant_id: str, actor_user_id: str) -> None:
    row = conn.execute(
        "select role from tenant_member where tenant_id=%s and user_id=%s",
        (tenant_id, actor_user_id),
    ).fetchone()
    role = _value(row, "role", 0) if row else None
    if role not in {"owner", "admin"}:
        raise PermissionError("configuration changes require tenant owner or admin")


def publish_override(
    conn,
    *,
    tenant_id: str,
    scope_type: str,
    scope_id: str,
    values: Mapping[str, object],
    actor_user_id: str,
    reason: str,
    operation: str = "apply",
    rollback_of_id: str | None = None,
) -> str:
    """Append a serialized override version; callers commit their transaction."""
    normalized = _validate_scopes(tenant_id, {"tenant": tenant_id, scope_type: scope_id})
    if operation not in {"apply", "detach", "rollback"}:
        raise ValueError("unsupported configuration operation")
    if not reason.strip():
        raise ValueError("configuration change reason is required")
    if operation == "detach" and values:
        raise ValueError("detach cannot contain values")
    if operation != "detach" and not values:
        raise ValueError(f"{operation} requires values")
    _require_admin(conn, tenant_id, actor_user_id)
    conn.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"config:{tenant_id}:{scope_type}:{normalized[scope_type]}",),
    )
    previous = conn.execute(
        """select id,version from configuration_override_version
            where tenant_id=%s and scope_type=%s and scope_id=%s
            order by version desc limit 1""",
        (tenant_id, scope_type, normalized[scope_type]),
    ).fetchone()
    version = (_value(previous, "version", 1) if previous else 0) + 1
    row = conn.execute(
        """insert into configuration_override_version(
             tenant_id,scope_type,scope_id,version,operation,values,supersedes_id,
             rollback_of_id,reason,created_by)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            scope_type,
            normalized[scope_type],
            version,
            operation,
            Jsonb(dict(values)),
            _value(previous, "id", 0) if previous else None,
            rollback_of_id,
            reason.strip(),
            actor_user_id,
        ),
    ).fetchone()
    return str(_value(row, "id", 0))


def detach_override(conn, **kwargs) -> str:
    return publish_override(conn, values={}, operation="detach", **kwargs)


def rollback_override(conn, *, rollback_to_id: str, **kwargs) -> str:
    tenant_id = kwargs["tenant_id"]
    target = conn.execute(
        "select values,scope_type,scope_id from configuration_override_version where tenant_id=%s and id=%s",
        (tenant_id, rollback_to_id),
    ).fetchone()
    if target is None:
        raise ValueError("rollback target does not exist in tenant")
    if (
        _value(target, "scope_type", 1) != kwargs["scope_type"]
        or _value(target, "scope_id", 2) != kwargs["scope_id"]
    ):
        raise ValueError("rollback target belongs to a different scope")
    return publish_override(
        conn,
        values=_value(target, "values", 0),
        operation="rollback",
        rollback_of_id=rollback_to_id,
        **kwargs,
    )
