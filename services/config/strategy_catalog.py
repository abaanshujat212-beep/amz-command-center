"""Safe, idempotent objective and strategy seed templates."""

from __future__ import annotations

from psycopg.types.json import Jsonb

OBJECTIVE_TEMPLATES = (
    ("profitability", "profitability", "Profitability", {"target_acos": 0.25}),
    ("growth", "growth", "Controlled growth", {"target_roas": 3.0}),
    ("efficiency", "efficiency", "Advertising efficiency", {"target_acos": 0.30}),
    ("launch", "launch", "Product launch", {"target_acos": 0.45}),
    ("defend", "defend", "Brand defence", {"target_acos": 0.35}),
)
STRATEGY_TEMPLATES = (
    ("conservative", "conservative", "Conservative", {"bid_step_pct": 0.05}),
    ("balanced", "balanced", "Balanced", {"bid_step_pct": 0.10}),
    ("growth", "growth", "Growth", {"bid_step_pct": 0.15}),
    ("harvest", "harvest", "Harvest", {"bid_step_pct": 0.08}),
    ("launch", "launch", "Launch", {"bid_step_pct": 0.10}),
)
SAFE_GUARDRAILS = {
    "min_bid": 0.02,
    "max_bid": 2.00,
    "max_change_pct": 0.10,
    "blast_radius_pct": 0.10,
    "max_data_age_hours": 48,
    "settlement_lag_days": 3,
}


def seed_templates(conn, tenant_id: str) -> tuple[int, int]:
    """Insert v1 templates disabled; existing tenant versions are untouched."""
    objectives: dict[str, str] = {}
    created_objectives = 0
    for code, mode, name, targets in OBJECTIVE_TEMPLATES:
        row = conn.execute(
            """insert into objective_version(
                   tenant_id,code,version,mode,name,enabled,targets,guardrails)
               values(%s,%s,1,%s,%s,false,%s,%s)
               on conflict(tenant_id,code,version) do nothing returning id""",
            (tenant_id, code, mode, name, Jsonb(targets), Jsonb(SAFE_GUARDRAILS)),
        ).fetchone()
        if row is not None:
            created_objectives += 1
            objectives[code] = str(row["id"] if isinstance(row, dict) else row[0])
        else:
            existing = conn.execute(
                "select id from objective_version where tenant_id=%s and code=%s and version=1",
                (tenant_id, code),
            ).fetchone()
            objectives[code] = str(existing["id"] if isinstance(existing, dict) else existing[0])
    created_strategies = 0
    for code, mode, name, settings in STRATEGY_TEMPLATES:
        objective_code = "growth" if code in {"growth", "launch"} else "profitability"
        row = conn.execute(
            """insert into strategy_version(
                   tenant_id,objective_version_id,code,version,mode,name,enabled,
                   settings,guardrails)
               values(%s,%s,%s,1,%s,%s,false,%s,%s)
               on conflict(tenant_id,code,version) do nothing returning id""",
            (
                tenant_id,
                objectives[objective_code],
                code,
                mode,
                name,
                Jsonb(settings),
                Jsonb(SAFE_GUARDRAILS),
            ),
        ).fetchone()
        created_strategies += int(row is not None)
    return created_objectives, created_strategies
