"""Rule evaluation engine.

One run = one pass over every enabled rule for one tenant:

    load rules -> query marts -> compile condition -> match entities
    -> resolve target value -> guardrails -> persist evaluation
    -> persist proposal (pending approval)

This process NEVER talks to Amazon. Applying a proposal is a separate, approved
step in services/actions. That separation is the safety model: the engine can
only ever suggest.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from services.rules import guardrails as gr
from services.rules.compiler import (
    RuleValidationError,
    compile_condition,
    render_reason,
    resolve_action,
)

# Which mart and value column each scope reads.
SCOPE_SOURCES: dict[str, dict[str, str]] = {
    "campaign": {
        "table": "mart_ppc_campaign_daily",
        "entity_id": "campaign_id",
        "value": "budget_amount",
    },
    "keyword": {
        "table": "mart_ppc_keyword_daily",
        "entity_id": "keyword_id",
        "value": "bid",
    },
    "search_term": {
        "table": "mart_ppc_search_term_daily",
        "entity_id": "search_term",
        "value": "bid",
    },
    "placement": {
        "table": "mart_ppc_placement_daily",
        "entity_id": "placement",
        "value": "placement_modifier",
    },
}


@dataclass
class RunSummary:
    run_id: str
    tenant_id: str
    rules_run: int = 0
    entities_evaluated: int = 0
    matched: int = 0
    proposed: int = 0
    blocked: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record_block(self, guard: gr.Guard) -> None:
        self.blocked[guard.value] = self.blocked.get(guard.value, 0) + 1

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "rules_run": self.rules_run,
            "entities_evaluated": self.entities_evaluated,
            "matched": self.matched,
            "proposed": self.proposed,
            "blocked": self.blocked,
            "errors": self.errors,
        }


def _load_settings(cur, tenant_id: str) -> gr.TenantGuardConfig:
    cur.execute(
        """select automation_enabled, dry_run, min_bid, max_bid,
                  max_daily_budget, max_changes_per_day
           from tenant_settings where tenant_id = %s""",
        (tenant_id,),
    )
    row = cur.fetchone()
    if row is None:
        return gr.TenantGuardConfig()  # no settings row = no consent. Fail closed.
    return gr.TenantGuardConfig(
        automation_enabled=row["automation_enabled"],
        dry_run=row["dry_run"],
        min_bid=float(row["min_bid"]),
        max_bid=float(row["max_bid"]),
        max_daily_budget=float(row["max_daily_budget"]),
        max_changes_per_day=row["max_changes_per_day"],
    )


def _base_context(cur, tenant_id: str, now: dt.datetime, through: dt.date) -> gr.RunContext:
    cur.execute(
        """select coalesce(applied_today, 0) as n,
                  coalesce(budget_delta_today, 0) as b
           from v_changes_today where tenant_id = %s""",
        (tenant_id,),
    )
    row = cur.fetchone() or {"n": 0, "b": 0}
    return gr.RunContext(
        now=now,
        data_through=through,
        data_loaded_at=now,
        changes_applied_today=int(row["n"]),
        budget_increase_today=float(row["b"]),
    )


def _fetch_candidates(cur, source: dict, rule: dict, where_sql: str, params: list, through: dt.date):
    """Aggregate the rule's lookback window, then evaluate the condition on it.

    Note the condition runs on AGGREGATED metrics, not on single days -- a rule
    must judge 14 days of behaviour, not yesterday's noise.
    """
    sql = f"""
        with agg as (
            select
                {source['entity_id']}::text        as entity_id,
                max({source['value']})             as current_value,
                sum(clicks)                        as clicks,
                sum(impressions)                   as impressions,
                sum(cost)                          as cost,
                sum(attributed_orders_7d)          as attributed_orders_7d,
                sum(attributed_sales_7d)           as attributed_sales_7d,
                sum(attributed_units_7d)           as attributed_units_7d,
                case when sum(attributed_sales_7d) > 0
                     then sum(cost) / sum(attributed_sales_7d) end as acos,
                case when sum(cost) > 0
                     then sum(attributed_sales_7d) / sum(cost) end as roas,
                case when sum(impressions) > 0
                     then sum(clicks)::numeric / sum(impressions) end as ctr,
                case when sum(clicks) > 0
                     then sum(attributed_orders_7d)::numeric / sum(clicks) end as cvr,
                case when sum(clicks) > 0
                     then sum(cost) / sum(clicks) end as cpc,
                max(asin)                          as asin
            from {source['table']}
            where tenant_id = %s
              and report_date >  %s - (%s || ' days')::interval
              and report_date <= %s
              and is_settled
            group by 1
        ),
        m as (
            select a.*,
                   null::numeric as tacos,
                   null::numeric as budget_utilisation,
                   null::integer as days_capped,
                   null::numeric as top_of_search_impression_share,
                   null::numeric as account_cvr,
                   false         as is_already_negative,
                   false         as exists_as_exact,
                   a.current_value as bid,
                   a.current_value as budget_amount
            from agg a
        )
        select m.*, e.break_even_acos, e.contribution_margin_pct,
               ({where_sql}) as _matched
        from m
        left join mart_sku_economics e
               on e.tenant_id = %s and e.asin = m.asin
        where m.clicks >= %s or m.impressions >= %s
    """
    args = [
        rule["tenant_id"], through, rule["lookback_days"], through,
        *params,
        rule["tenant_id"], rule["min_clicks"], rule["min_impressions"],
    ]
    cur.execute(sql, args)
    return cur.fetchall()


def evaluate_tenant(
    conn: psycopg.Connection,
    tenant_id: str,
    *,
    now: dt.datetime | None = None,
    data_through: dt.date | None = None,
    force_dry_run: bool = False,
) -> RunSummary:
    now = now or dt.datetime.now(dt.timezone.utc)
    summary = RunSummary(run_id=str(uuid.uuid4()), tenant_id=tenant_id)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))

        cfg = _load_settings(cur, tenant_id)
        if force_dry_run:
            cfg = gr.TenantGuardConfig(**{**cfg.__dict__, "dry_run": True})

        through = data_through or (now.date() - dt.timedelta(days=cfg.settlement_lag_days))
        base = _base_context(cur, tenant_id, now, through)

        cur.execute(
            """select id, tenant_id, code, name, scope, condition_jsonb, action_jsonb,
                      lookback_days, min_clicks, min_impressions
               from rule
               where tenant_id = %s and enabled = true
               order by priority asc, code asc""",
            (tenant_id,),
        )
        rules = cur.fetchall()

        # One entity gets at most one change per run. Lower priority wins.
        claimed: set[tuple[str, str]] = set()

        for rule in rules:
            source = SCOPE_SOURCES.get(rule["scope"])
            if source is None:
                summary.errors.append(f"{rule['code']}: unsupported scope {rule['scope']}")
                continue

            try:
                where_sql, params = compile_condition(rule["condition_jsonb"])
            except RuleValidationError as exc:
                # A broken rule is disabled, not retried forever.
                summary.errors.append(f"{rule['code']}: {exc}")
                cur.execute(
                    "update rule set enabled = false, updated_at = now() where id = %s",
                    (rule["id"],),
                )
                continue

            summary.rules_run += 1
            rows = _fetch_candidates(cur, source, rule, where_sql, params, through)
            matched = [r for r in rows if r["_matched"]]
            summary.entities_evaluated += len(rows)
            summary.matched += len(matched)

            # Blast radius is judged per rule against that rule's population.
            ctx = gr.RunContext(
                **{
                    **base.__dict__,
                    "entities_evaluated": len(rows),
                    "entities_matched": len(matched),
                }
            )

            for row in matched:
                key = (rule["scope"], str(row["entity_id"]))
                if key in claimed:
                    continue

                metrics = {k: v for k, v in row.items() if not k.startswith("_")}
                current = row["current_value"]
                current = float(current) if current is not None else None

                try:
                    target = resolve_action(rule["action_jsonb"], current)
                except RuleValidationError as exc:
                    summary.errors.append(f"{rule['code']}/{key[1]}: {exc}")
                    continue

                cur.execute(
                    """select last_applied_at from v_last_applied_action
                       where tenant_id = %s and entity_type = %s and entity_id = %s""",
                    (tenant_id, rule["scope"], key[1]),
                )
                last = cur.fetchone()
                entity_ctx = gr.RunContext(
                    **{**ctx.__dict__, "last_applied_at": last["last_applied_at"] if last else None}
                )

                proposal = gr.Proposal(
                    entity_type=rule["scope"],
                    entity_id=key[1],
                    action_type=rule["action_jsonb"]["type"],
                    before_value=current,
                    after_value=target,
                    clicks=int(row["clicks"] or 0),
                    impressions=int(row["impressions"] or 0),
                    break_even_acos=(
                        float(row["break_even_acos"]) if row["break_even_acos"] is not None else None
                    ),
                )
                decision = gr.check(
                    proposal, cfg, entity_ctx,
                    min_clicks=rule["min_clicks"],
                    min_impressions=rule["min_impressions"],
                )

                reason = render_reason(
                    rule["action_jsonb"].get("reason_template", rule["name"]),
                    {**metrics, "lookback_days": rule["lookback_days"]},
                )

                # Every evaluation is persisted -- including blocked ones.
                # Invisible automation is untrustworthy automation.
                cur.execute(
                    """insert into rule_evaluation
                         (tenant_id, rule_id, run_id, entity_type, entity_id,
                          data_through, matched, metrics_snapshot, proposed_action,
                          reason_text, blocked_by)
                       values (%s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s)
                       returning id""",
                    (
                        tenant_id, rule["id"], summary.run_id, rule["scope"], key[1],
                        through,
                        json.dumps(metrics, default=str),
                        json.dumps(
                            {
                                "action_type": proposal.action_type,
                                "before": current,
                                "after": decision.value,
                                "clamped": decision.clamped,
                                "notes": decision.notes,
                            },
                            default=str,
                        ),
                        reason,
                        decision.blocked_by.value if decision.blocked_by else None,
                    ),
                )
                evaluation_id = cur.fetchone()["id"]

                if not decision.allowed:
                    if decision.blocked_by:
                        summary.record_block(decision.blocked_by)
                    # Blast radius halts the whole rule, not just one entity.
                    if decision.blocked_by is gr.Guard.BLAST_RADIUS:
                        cur.execute(
                            """insert into alert (tenant_id, kind, severity, title, detail)
                               values (%s, 'blast_radius_halt', 'critical', %s, %s)""",
                            (
                                tenant_id,
                                f"Rule '{rule['code']}' matched too many entities; halted",
                                json.dumps(
                                    {"matched": len(matched), "evaluated": len(rows)}
                                ),
                            ),
                        )
                        break
                    continue

                idem = f"{summary.run_id}:{rule['code']}:{key[1]}"
                cur.execute(
                    """insert into action
                         (tenant_id, rule_id, evaluation_id, entity_type, entity_id,
                          action_type, before_value, after_value, status, reason_text,
                          clamped, clamp_note, idempotency_key)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                       on conflict (tenant_id, idempotency_key) do nothing""",
                    (
                        tenant_id, rule["id"], evaluation_id, rule["scope"], key[1],
                        proposal.action_type,
                        json.dumps({"value": current}),
                        json.dumps({"value": decision.value}),
                        reason,
                        decision.clamped,
                        "; ".join(decision.notes) or None,
                        idem,
                    ),
                )
                summary.proposed += 1
                claimed.add(key)

        cur.execute(
            """insert into pipeline_run (tenant_id, pipeline, status, started_at,
                                         finished_at, detail)
               values (%s, 'rules_evaluate', %s, %s, now(), %s)""",
            (
                tenant_id,
                "failed" if summary.errors else "success",
                now,
                json.dumps(summary.as_dict(), default=str),
            ),
        )

    conn.commit()
    return summary


if __name__ == "__main__":
    import argparse
    import os

    p = argparse.ArgumentParser()
    p.add_argument("--tenant", required=True)
    p.add_argument("--dry-run", action="store_true", default=True)
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")
    with psycopg.connect(url) as conn:
        result = evaluate_tenant(conn, args.tenant, force_dry_run=args.dry_run)
    print(json.dumps(result.as_dict(), indent=2, default=str))
