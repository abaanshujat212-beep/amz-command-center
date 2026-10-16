"""Rule evaluation engine.

load rules -> aggregate marts -> apply compiled condition in SQL -> guardrails
-> persist evaluation -> queue a pending proposal.

This process never talks to Amazon. Applying is a separate approved step in
services/actions. The engine can only ever suggest.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from dataclasses import asdict, dataclass, field

import psycopg
from psycopg.rows import dict_row

from packages.shared.action_capabilities import capability
from services.actions.human_control import active_control
from services.rules import guardrails as gr
from services.rules.compiler import (
    RuleValidationError,
    compile_condition,
    render_reason,
    resolve_action,
)
from services.rules.evidence import build_guardrail_context
from services.rules.freshness import resolve_source_freshness
from services.rules.harvest import plan_harvest, record_lineage
from services.rules.protections import active_protection
from services.rules.query import SCOPE_SOURCES, fetch_candidates
from services.rules.recommendations import build_metadata, configuration_snapshots
from services.rules.settings import load_tenant_guard_config


@dataclass
class RunSummary:
    run_id: str
    tenant_id: str
    rules_run: int = 0
    entities_evaluated: int = 0
    matched: int = 0
    proposed: int = 0  # changes queued for approval
    flagged: int = 0  # diagnostics raised (nothing to approve)
    blocked: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    source_freshness: dict = field(default_factory=dict)

    def block(self, guard) -> None:
        self.blocked[guard.value] = self.blocked.get(guard.value, 0) + 1


def _usage_today(cur, tenant_id: str) -> tuple[int, float]:
    cur.execute(
        "select coalesce(applied_today,0) n, coalesce(budget_delta_today,0) b"
        " from v_changes_today where tenant_id = %s",
        (tenant_id,),
    )
    r = cur.fetchone() or {"n": 0, "b": 0}
    return int(r["n"]), float(r["b"])


def _last_applied(cur, tenant_id: str, scope: str, entity_id: str):
    cur.execute(
        "select last_applied_at from v_last_applied_action"
        " where tenant_id = %s and entity_type = %s and entity_id = %s",
        (tenant_id, scope, entity_id),
    )
    r = cur.fetchone()
    return r["last_applied_at"] if r else None


def evaluate_tenant(
    conn: psycopg.Connection,
    tenant_id: str,
    *,
    now: dt.datetime | None = None,
    through: dt.date | None = None,
) -> RunSummary:
    now = now or dt.datetime.now(dt.timezone.utc)
    started = time.monotonic()
    run_id = str(uuid.uuid4())
    s = RunSummary(run_id=run_id, tenant_id=tenant_id)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cfg = load_tenant_guard_config(cur, tenant_id)
        objective_snapshot, strategy_snapshot, configuration_version = configuration_snapshots(cur, tenant_id)
        cur.execute(
            """insert into optimizer_run(id,tenant_id,run_key,engine_version,configuration_version,
                   objective_snapshot,strategy_snapshot,started_at)
               values(%s,%s,%s,'rules-engine-v1',%s,%s,%s,%s)
               on conflict(tenant_id,run_key) do nothing""",
            (run_id, tenant_id, run_id, configuration_version, json.dumps(objective_snapshot), json.dumps(strategy_snapshot), now),
        )
        through = through or (now.date() - dt.timedelta(days=cfg.settlement_lag_days))
        changes_today, budget_today = _usage_today(cur, tenant_id)

        cur.execute(
            "select id, code, scope, condition_jsonb, action_jsonb, lookback_days,"
            " min_clicks, min_impressions from rule"
            " where tenant_id = %s and enabled = true order by priority, code",
            (tenant_id,),
        )
        rules = cur.fetchall()
        claimed: set[tuple[str, str]] = set()

        for rule in rules:
            if rule["scope"] not in SCOPE_SOURCES:
                s.errors.append(f"{rule['code']}: scope '{rule['scope']}' not wired yet")
                continue
            try:
                where_sql, where_params = compile_condition(rule["condition_jsonb"])
            except RuleValidationError as exc:
                # A broken rule is disabled, not retried on every run.
                s.errors.append(f"{rule['code']}: {exc}")
                cur.execute(
                    "update rule set enabled = false, updated_at = now() where id = %s",
                    (rule["id"],),
                )
                continue

            action_type = rule["action_jsonb"]["type"]
            # A diagnostic changes nothing, so it neither respects nor consumes
            # the one-rule-per-entity claim. Letting it claim would mean a
            # "low CTR" finding silently cancelling a bid change on the same
            # keyword -- two unrelated outputs competing for one slot.
            diagnostic = gr.is_diagnostic(action_type)

            settled_cutoff = now.date() - dt.timedelta(days=cfg.settlement_lag_days)
            freshness = resolve_source_freshness(
                cur,
                tenant_id=tenant_id,
                scope=rule["scope"],
                now=now,
                settled_cutoff=settled_cutoff,
                max_age_hours=cfg.max_data_age_hours,
            )
            s.source_freshness[rule["scope"]] = freshness.as_dict()
            if not freshness.usable:
                s.blocked[freshness.block_reason] = s.blocked.get(freshness.block_reason, 0) + 1
                continue

            s.rules_run += 1
            rows = fetch_candidates(
                cur,
                tenant_id=tenant_id,
                scope=rule["scope"],
                lookback_days=rule["lookback_days"],
                through=freshness.data_through,
                where_sql=where_sql,
                where_params=where_params,
            )
            s.entities_evaluated += len(rows)
            matched = [r for r in rows if r["matched"]]
            s.matched += len(matched)

            for row in matched:
                key = (rule["scope"], row["entity_id"])
                if not diagnostic and key in claimed:
                    continue  # a higher-priority rule already owns this entity

                current = row.get("current_value")
                current = float(current) if current is not None else None
                try:
                    target = resolve_action(rule["action_jsonb"], current)
                except RuleValidationError as exc:
                    s.errors.append(f"{rule['code']}/{key[1]}: {exc}")
                    continue

                proposal = gr.Proposal(
                    entity_type=rule["scope"],
                    entity_id=row["entity_id"],
                    action_type=action_type,
                    before_value=current,
                    after_value=target,
                    clicks=int(row.get("clicks") or 0),
                    impressions=int(row.get("impressions") or 0),
                    break_even_acos=row.get("break_even_acos"),
                )
                ctx = gr.RunContext(
                    now=now,
                    data_through=freshness.data_through,
                    data_loaded_at=freshness.data_loaded_at,
                    changes_applied_today=changes_today,
                    budget_increase_today=budget_today,
                    entities_evaluated=len(rows),
                    entities_matched=len(matched),
                    last_applied_at=_last_applied(cur, tenant_id, rule["scope"], key[1]),
                )
                decision = gr.check(
                    proposal,
                    cfg,
                    ctx,
                    rule["min_clicks"],
                    rule["min_impressions"],
                )
                protection = active_protection(
                    cur,
                    tenant_id=tenant_id,
                    entity_type=rule["scope"],
                    entity_value=key[1],
                    product_scope=str(row.get("asin") or "*"),
                    action_type=action_type,
                    now=now,
                )
                if protection.blocked:
                    decision.block(
                        gr.Guard.PROTECTED_ENTITY,
                        f"{protection.policy} protection {protection.protection_id}: "
                        f"{protection.reason}",
                    )
                ownership = active_control(
                    cur,
                    tenant_id=tenant_id,
                    entity_type=rule["scope"],
                    entity_id=key[1],
                    product_scope=str(row.get("asin") or "*"),
                    now=now,
                )
                if ownership.blocked:
                    decision.block(
                        gr.Guard.HUMAN_CONTROL,
                        f"{ownership.state} control {ownership.control_id}: {ownership.reason}",
                    )
                harvest = None
                if rule["scope"] == "search_term" and action_type == "create_keyword":
                    harvest = plan_harvest(
                        cur,
                        tenant_id=tenant_id,
                        search_term=key[1],
                        lookback_days=rule["lookback_days"],
                        through=freshness.data_through,
                    )
                    if harvest.blocked_by:
                        decision.block(gr.Guard(harvest.blocked_by), harvest.note)

                metrics = {k: v for k, v in row.items() if k != "matched"}
                metrics["source_freshness"] = freshness.as_dict()
                metrics["guardrail_context"] = build_guardrail_context(
                    entities_evaluated=len(rows),
                    entities_matched=len(matched),
                    min_clicks=rule["min_clicks"],
                    min_impressions=rule["min_impressions"],
                    freshness=freshness,
                )
                if harvest is not None:
                    metrics["harvest_routing"] = harvest.evidence()
                reason = render_reason(
                    rule["action_jsonb"].get("reason_template", rule["code"]),
                    metrics,
                )
                if harvest is not None:
                    reason = f"{reason} Routing: {harvest.routing_reason}"

                metadata = build_metadata(
                    action_type=action_type,
                    lookback_days=rule["lookback_days"],
                    metrics=metrics,
                    blocked_by=decision.blocked_by.value if decision.blocked_by else None,
                    objective_snapshot=objective_snapshot,
                    strategy_snapshot=strategy_snapshot,
                )
                contract = metadata.as_dict()

                cur.execute(
                    "insert into rule_evaluation (tenant_id, rule_id, run_id,"
                    " entity_type, entity_id, data_through, matched,"
                    " metrics_snapshot, proposed_action, reason_text, blocked_by,recommendation_type,"
                    " confidence,risk,lookback_days,objective_snapshot,strategy_snapshot,economic_effect,expected_behavior)"
                    " values (%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (
                        tenant_id,
                        rule["id"],
                        run_id,
                        rule["scope"],
                        key[1],
                        freshness.data_through,
                        json.dumps(metrics, default=str),
                        json.dumps(
                            {
                                "type": action_type,
                                "value": decision.value,
                                **(
                                    {"destination": harvest.destination}
                                    if harvest is not None and harvest.destination
                                    else {}
                                ),
                            },
                            default=str,
                        ),
                        reason,
                        decision.blocked_by.value if decision.blocked_by else None,
                        contract["recommendation_type"],
                        contract["confidence"],
                        contract["risk"],
                        contract["lookback_days"],
                        json.dumps(contract["objective_snapshot"], default=str),
                        json.dumps(contract["strategy_snapshot"], default=str),
                        json.dumps(contract["economic_effect"], default=str),
                        json.dumps(contract["expected_behavior"], default=str),
                    ),
                )
                evaluation_id = cur.fetchone()["id"]

                action_id = None

                if not decision.allowed:
                    s.block(decision.blocked_by)
                else:
                    # Existing action remains the one authoritative approval queue.
                    cur.execute(
                        "insert into action (tenant_id, rule_id, evaluation_id,entity_type,entity_id,action_type,"
                        " before_value,after_value,reason_text,clamped,clamp_note,idempotency_key,recommendation_type,"
                        " confidence,risk,lookback_days,objective_snapshot,strategy_snapshot,economic_effect,expected_behavior)"
                        " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        " on conflict (tenant_id,idempotency_key) do nothing returning id",
                        (tenant_id,rule["id"],evaluation_id,rule["scope"],key[1],action_type,
                         json.dumps({"value":current}),json.dumps({"value":decision.value,"diagnostic":True} if diagnostic else {"value":decision.value,**({"destination":harvest.destination} if harvest is not None else {})}),
                         reason,decision.clamped,"; ".join(decision.notes) or None,f"{run_id}:{rule['code']}:{key[1]}",
                         contract["recommendation_type"],contract["confidence"],contract["risk"],contract["lookback_days"],
                         json.dumps(contract["objective_snapshot"],default=str),json.dumps(contract["strategy_snapshot"],default=str),
                         json.dumps(contract["economic_effect"],default=str),json.dumps(contract["expected_behavior"],default=str)),
                    )
                    queued = cur.fetchone()
                    action_id = queued["id"] if queued else None
                    if harvest is not None and queued is not None:
                        record_lineage(
                            cur,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            evaluation_id=evaluation_id,
                            action_id=action_id,
                            plan=harvest,
                        )
                    if diagnostic:
                        s.flagged += 1
                    else:
                        claimed.add(key)
                        s.proposed += 1

                metric_keys = sorted(k for k, value in metrics.items() if value is not None and k not in {"source_freshness","guardrail_context","harvest_routing"})
                completeness = "complete" if freshness.usable and metrics.get("break_even_acos") is not None else "partial"
                cur.execute(
                    """insert into recommendation_evidence(tenant_id,optimizer_run_id,evaluation_id,action_id,
                           evidence_kind,source_type,source_ref,observed_at,data_through,completeness,metric_keys,detail)
                       values(%s,%s,%s,%s,'metric_snapshot','dbt_mart',%s,%s,%s,%s,%s,%s)""",
                    (tenant_id,run_id,evaluation_id,action_id,f"{rule['scope']}:{freshness.data_through}",
                     freshness.data_loaded_at or now,freshness.data_through,completeness,json.dumps(metric_keys),
                     json.dumps({"blocked_by":decision.blocked_by.value if decision.blocked_by else None,"economics":contract["economic_effect"]},default=str)),
                )
                cur.execute(
                    """insert into recommendation_evidence(tenant_id,optimizer_run_id,evaluation_id,action_id,
                           evidence_kind,source_type,source_ref,observed_at,data_through,completeness,detail)
                       values(%s,%s,%s,%s,'capability','capability_registry','action_capabilities:v1',%s,%s,'complete',%s)""",
                    (tenant_id,run_id,evaluation_id,action_id,now,freshness.data_through,
                     json.dumps(asdict(capability(rule["scope"],action_type)))),
                )

        # Column names must match 0001_tenancy.sql: dataset (not pipeline),
        # rows_loaded, detail. Getting this wrong rolls back the entire run.
        cur.execute(
            "insert into pipeline_run (tenant_id, dataset, date_to, status,"
            " rows_loaded, finished_at, detail)"
            " values (%s, 'rules_evaluate', %s, %s, %s, now(), %s)",
            (
                tenant_id,
                through,
                "partial" if s.errors else "success",
                s.proposed + s.flagged,
                json.dumps(asdict(s), default=str),
            ),
        )
        finished = dt.datetime.now(dt.timezone.utc)
        cur.execute(
            """update optimizer_run set status=%s,entities_evaluated=%s,recommendations_emitted=%s,
                   entities_skipped=%s,failures=%s,finished_at=%s,duration_ms=%s
               where tenant_id=%s and id=%s and status='running'""",
            ("partial" if s.errors else "succeeded",s.entities_evaluated,s.proposed+s.flagged,
             max(0,s.entities_evaluated-s.matched)+sum(s.blocked.values()),len(s.errors),finished,
             int((time.monotonic()-started)*1000),tenant_id,run_id),
        )
        conn.commit()

    return s
