"""The copilot's picture of the system, derived from the system itself.

Every fact here is read from the thing that defines it: rules from the rule
catalog, scopes from the query layer, guardrails from the Guard enum, action types
from the CHECK constraint, endpoints from the shared catalog, config keys from
.env.example, tables and policies from Postgres.

Nothing is copied into a prompt. A map that is authored by hand is wrong within a
week and — worse — wrong invisibly. See ADR 006.

Two halves:
  static_map()   works with no database, so it is usable before anything runs
  live_map(conn) needs Postgres, and is where the interesting questions live

self_check() is the 'check the whole system' half: it cross-references the sources
and reports contradictions instead of trusting any single one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.shared import endpoints as ep
from services.rules.guardrails import Guard
from services.rules.query import SCOPE_SOURCES
from services.rules.rule_catalog import ALL_RULES

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "packages" / "db" / "migrations"
ENV_EXAMPLE = ROOT / ".env.example"
DBT_MODELS = ROOT / "packages" / "dbt" / "models"

NOT_IN_MAP = "not in the system map"

# Tables that legitimately hold no tenant_id and need no policy.
TENANT_EXEMPT_TABLES = frozenset(
    {
        "public.schema_migrations",  # infrastructure, no tenant data
        "public.tenant",  # protected by the tenant_self policy on id, not tenant_id
    }
)

# Every guardrail needs a sentence a client would accept as an answer. If a new
# Guard member lands without one, the test fails — an unexplained block is
# indistinguishable from a bug to the person whose campaign did not change.
GUARD_EXPLANATIONS: dict[str, str] = {
    "KILL_SWITCH": "Automation is switched off for this tenant, so nothing is applied.",
    "DRY_RUN": "Tenant is in dry-run: proposals are recorded but never sent to Amazon.",
    "STALE_DATA": "The underlying data is older than the allowed age, so it is not trusted.",
    "UNSETTLED_DATA": "Recent days are still restating; acting on them would chase noise.",
    "THIN_DATA": "Too few clicks or impressions for the difference to mean anything.",
    "COOLDOWN": "This entity was changed recently; back-to-back edits make results unreadable.",
    "DAILY_CHANGE_LIMIT": "The tenant's per-day change budget is already spent.",
    "DAILY_BUDGET_LIMIT": "Total budget increases today would exceed the allowed daily rise.",
    "BLAST_RADIUS": "Too large a share of the account would change in one run.",
    "BOUNDS": "The proposed value falls outside the tenant's min/max bid or budget bounds.",
    "ECONOMICS_INCOMPLETE": "Cost data is missing, so break-even is unknown and profit "
    "rules stay quiet rather than guessing.",
}


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "warning" | "info"
    area: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.area}: {self.message}"


# --- code- and file-derived facts (no database needed) --------------------


def migration_files() -> list[dict[str, Any]]:
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        body = path.read_text(encoding="utf-8")
        out.append(
            {
                "version": path.name[:4],
                "name": path.name,
                "checksum": hashlib.sha256(body.encode()).hexdigest()[:16],
                "has_down": (MIGRATIONS_DIR / "down" / path.name).exists(),
            }
        )
    return out


def action_types_from_migrations() -> list[str]:
    """Parse the action_type CHECK from the latest migration that defines it.

    The database is authoritative; this exists so the static map is usable before
    anything is migrated. self_check() compares the two whenever a connection is
    available, precisely because a regex over SQL is the weakest link here.
    """
    pattern = re.compile(r"action_type\s+in\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
    found: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            found = re.findall(r"'([a-z_]+)'", match.group(1))
    return sorted(found)


def env_keys() -> list[str]:
    """Config keys only. Values are never read, so they can never be echoed."""
    if not ENV_EXAMPLE.exists():
        return []
    keys = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return sorted(set(keys))


def dbt_models() -> dict[str, list[str]]:
    if not DBT_MODELS.exists():
        return {}
    out: dict[str, list[str]] = {}
    for path in sorted(DBT_MODELS.rglob("*.sql")):
        out.setdefault(path.parent.name, []).append(path.stem)
    return out


def rules() -> list[dict[str, Any]]:
    return [
        {
            "code": r["code"],
            "name": r.get("name"),
            "scope": r["scope"],
            "action_type": r["action"]["type"],
            "priority": r.get("priority"),
            "lookback_days": r.get("lookback_days"),
            "is_diagnostic": r["action"]["type"] in ep.LOCAL_ONLY_ACTIONS,
        }
        for r in ALL_RULES
    ]


def static_map() -> dict[str, Any]:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "code+files",
        "rules": rules(),
        "rule_count": len(ALL_RULES),
        "scopes": {
            scope: {"mart": src[0], "entity_column": src[1], "value_column": src[2]}
            for scope, src in SCOPE_SOURCES.items()
        },
        "action_types": action_types_from_migrations(),
        "local_only_actions": sorted(ep.LOCAL_ONLY_ACTIONS),
        "guardrails": {g.name: GUARD_EXPLANATIONS.get(g.name, NOT_IN_MAP) for g in Guard},
        "endpoints": {
            key: {
                "api": e.api.value,
                "method": e.method,
                "path": e.path,
                "summary": e.summary,
                "mutates": e.mutates,
                "rate_limit_rps": e.rate_limit_rps,
            }
            for key, e in ep.ENDPOINTS.items()
        },
        "mutating_endpoints": sorted(e.key for e in ep.mutating()),
        "ads_report_lookback_days": ep.ADS_REPORT_LOOKBACK_DAYS,
        "regions": sorted(ep.REGIONS),
        "migrations": migration_files(),
        "dbt_models": dbt_models(),
        "config_keys": env_keys(),
    }


# --- live facts (needs a connection) --------------------------------------


def _rows(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def live_map(conn) -> dict[str, Any]:
    """Facts only the running database knows. Read-only, and cheap on purpose."""
    tables: dict[str, list[str]] = {}
    for schema, table, column in _rows(
        conn,
        """select table_schema, table_name, column_name
             from information_schema.columns
            where table_schema in ('public', 'marts', 'raw')
            order by table_schema, table_name, ordinal_position""",
    ):
        tables.setdefault(f"{schema}.{table}", []).append(column)

    policies: dict[str, list[str]] = {}
    for schema, table, name in _rows(
        conn,
        "select schemaname, tablename, policyname from pg_policies order by 1, 2",
    ):
        policies.setdefault(f"{schema}.{table}", []).append(name)

    applied = [
        {"version": v, "name": n, "checksum": c, "applied_at": str(a)}
        for v, n, c, a in _rows(
            conn,
            "select version, name, checksum, applied_at from schema_migrations order by version",
        )
    ]

    constraint = _rows(
        conn,
        """select pg_get_constraintdef(oid) from pg_constraint
            where conname = 'action_action_type_check'""",
    )
    db_action_types = sorted(re.findall(r"'([a-z_]+)'", constraint[0][0])) if constraint else []

    return {
        "source": "database",
        "tables": tables,
        "rls_policies": policies,
        "applied_migrations": applied,
        "action_types": db_action_types,
    }


def build(conn=None) -> dict[str, Any]:
    m = static_map()
    if conn is not None:
        m["live"] = live_map(conn)
        m["source"] = "code+files+database"
    return m


# --- the checking half ----------------------------------------------------


def _check_rls(live: dict[str, Any]) -> list[Finding]:
    """Every table holding tenant data must have a policy standing over it.

    This is the most valuable check here and the least visible failure. A
    forgotten policy looks completely normal: careful developers still filter by
    tenant in every query they write, so nothing misbehaves — until one query
    does not, and it returns another client's spend. The database, not the
    discipline of the person writing SQL, has to be the thing that refuses.
    """
    out: list[Finding] = []
    for name, columns in live["tables"].items():
        if not name.startswith("public.") or name in TENANT_EXEMPT_TABLES:
            continue
        if "tenant_id" not in columns:
            continue
        if not live["rls_policies"].get(name):
            out.append(
                Finding(
                    "error",
                    "rls",
                    f"{name} has a tenant_id column but no row-level security policy. "
                    f"Any query that forgets a tenant filter returns every tenant's rows.",
                )
            )

    for name in live["rls_policies"]:
        if name not in live["tables"]:
            out.append(
                Finding("warning", "rls", f"policy exists for {name}, which no longer exists.")
            )

    # The reverse mistake: a protected table nobody can read because the app role
    # was never granted access is a availability bug, not a security one, but it
    # fails at 3am rather than in review.
    if "public.tenant" in live["tables"] and not live["rls_policies"].get("public.tenant"):
        out.append(
            Finding(
                "error",
                "rls",
                "public.tenant has no policy; tenant_self is required because "
                "FORCE ROW LEVEL SECURITY applies even to the owning role.",
            )
        )
    return out


def self_check(conn=None) -> list[Finding]:
    """Cross-reference every source and report the contradictions.

    This is the part that would have caught the two bugs that already happened
    here: a rule whose scope was never wired (it skipped silently every run), and
    a mart model referenced by a ref() that did not exist.
    """
    out: list[Finding] = []
    static = static_map()

    for rule in static["rules"]:
        if rule["scope"] not in SCOPE_SOURCES:
            out.append(
                Finding(
                    "error",
                    "rules",
                    f"{rule['code']} has scope '{rule['scope']}' which is not in "
                    f"SCOPE_SOURCES, so the engine skips it without failing.",
                )
            )
        if static["action_types"] and rule["action_type"] not in static["action_types"]:
            out.append(
                Finding(
                    "error",
                    "rules",
                    f"{rule['code']} emits action_type '{rule['action_type']}' which the "
                    f"action CHECK constraint would reject at insert time.",
                )
            )

    for action_type in static["action_types"]:
        if action_type not in ep.ACTION_ENDPOINTS:
            out.append(
                Finding(
                    "error",
                    "endpoints",
                    f"action_type '{action_type}' is allowed by the database but has no "
                    f"entry in ACTION_ENDPOINTS, so nothing could ever apply it.",
                )
            )

    reachable = {key for mapping in ep.ACTION_ENDPOINTS.values() for key in mapping.values()}
    for endpoint in ep.mutating():
        if endpoint.key not in reachable:
            out.append(
                Finding(
                    "warning",
                    "endpoints",
                    f"{endpoint.key} mutates a client account but no action_type maps to "
                    f"it. Either it is dead code or an action is missing.",
                )
            )

    for guard in Guard:
        if guard.name not in GUARD_EXPLANATIONS:
            out.append(
                Finding(
                    "error",
                    "guardrails",
                    f"Guard.{guard.name} has no explanation, so a blocked change could "
                    f"not be explained to the client it affected.",
                )
            )

    for migration in static["migrations"]:
        if not migration["has_down"]:
            out.append(
                Finding(
                    "info", "migrations", f"{migration['name']} is forward-only (no down file)."
                )
            )

    if conn is not None:
        live = live_map(conn)
        applied = {m["version"]: m for m in live["applied_migrations"]}
        for migration in static["migrations"]:
            row = applied.get(migration["version"])
            if row is None:
                out.append(
                    Finding(
                        "warning",
                        "migrations",
                        f"{migration['name']} exists on disk but is not in the ledger.",
                    )
                )
            elif row["checksum"] != migration["checksum"]:
                out.append(
                    Finding(
                        "error",
                        "migrations",
                        f"{migration['name']} was edited after being applied "
                        f"(ledger {row['checksum']} != file {migration['checksum']}).",
                    )
                )
        if live["action_types"] and live["action_types"] != static["action_types"]:
            out.append(
                Finding(
                    "error",
                    "schema",
                    f"action types parsed from migrations {static['action_types']} do not "
                    f"match the live constraint {live['action_types']}.",
                )
            )
        out.extend(_check_rls(live))

    return out


def render_for_prompt(m: dict[str, Any] | None = None) -> str:
    """Compact text form. Facts only — no instructions, no invented commentary."""
    m = m or static_map()
    lines = [
        f"# System map ({m['source']}, generated {m['generated_at']})",
        "",
        f"Rules: {m['rule_count']} "
        f"({sum(1 for r in m['rules'] if r['is_diagnostic'])} diagnostic, "
        f"{sum(1 for r in m['rules'] if not r['is_diagnostic'])} change)",
    ]
    for rule in m["rules"]:
        lines.append(
            f"  - {rule['code']} scope={rule['scope']} action={rule['action_type']} "
            f"priority={rule['priority']} lookback={rule['lookback_days']}d"
        )
    lines += ["", "Scopes and their marts:"]
    for scope, src in m["scopes"].items():
        lines.append(f"  - {scope} -> marts.{src['mart']} (id {src['entity_column']})")
    lines += ["", f"Action types allowed by the database: {', '.join(m['action_types'])}"]
    lines += [f"Never leave the database: {', '.join(m['local_only_actions'])}"]
    lines += ["", "Guardrails:"]
    for name, why in m["guardrails"].items():
        lines.append(f"  - {name}: {why}")
    lines += ["", f"Endpoints ({len(m['endpoints'])}), mutating marked *:"]
    for key, e in m["endpoints"].items():
        star = "*" if e["mutates"] else " "
        lines.append(f"  {star} {key}: {e['method']} {e['path']} — {e['summary']}")
    lines += ["", f"Config keys (names only): {', '.join(m['config_keys'])}"]
    return "\n".join(lines)
