"""Rule evaluation engine.

load rules -> aggregate marts -> apply compiled condition in SQL -> guardrails
-> persist evaluation -> queue a pending proposal.

This process never talks to Amazon. Applying is a separate approved step in
services/actions. The engine can only ever suggest.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass, field

import psycopg
from psycopg.rows import dict_row

from services.rules import guardrails as gr
from services.rules.compiler import (
    RuleValidationError,
    compile_condition,
    render_reason,
    resolve_action,
)
from services.rules.query import SCOPE_SOURCES, fetch_candidates


@dataclass
class RunSummary:
    run_id: str
    tenant_id: str
    rules_run: int = 0
    entities_evaluated: int = 0
    matched: int = 0
    proposed: int = 0          # changes queued for approval
    flagged: int = 0           # diagnostics raised (nothing to approve)
    blocked: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def block(self, guard) -> None:
        self.blocked[guard.value] = self.blocked.get(guard.value, 0) + 1


def _settings(cur, tenant_id: str) -> gr.TenantGuardConfig:
    cur.execute(
        "select automation_enabled, dry_run, min_bid, max_bid, max_daily_budget,"
        " max_changes_per_day from tenant_settings where tenant_id = %s",
        (tenant_id,),
    )
    r = cur.fetchone()
    if r is None:
        return gr.TenantGuardConfig()  # no settings row = no consent, fail closed
    return gr.TenantGuardConfig(
        automation_enabled=r["automation_enabled"],
        dry_run=r["dry_run"],
        min_bid=float(r["min_bid"]),
        max_bid=float(r["max_bid"]),
        max_daily_budget=float(r["max_daily_budget"]),
        max_changes_per_day=r["max_changes_per_day"],
    )


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
    run_id = str(uuid.uuid4())
    s = RunSummary(run_id=run_id, tenant_id=tenant_id)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cfg = _settings(cur, tenant_id)
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

            s.rules_run += 1
            rows = fetch_candidates(
                cur,
                tenant_id=tenant_id,
                scope=rule["scope"],
                lookback_days=rule["lookback_days"],
                through=through,
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
                    data_through=through,
                    data_loaded_at=now,
                    changes_applied_today=changes_today,
                    budget_increase_today=budget_today,
                    entities_evaluated=len(rows),
                    entities_matched=len(matched),
                    last_applied_at=_last_applied(cur, tenant_id, rule["scope"], key[1]),
                )
                decision = gr.check(
                    proposal, cfg, ctx, rule["min_clicks"], rule["min_impressions"]
                )

                metrics = {k: v for k, v in row.items() if k != "matched"}
                reason = render_reason(
                    rule["action_jsonb"].get("reason_template", rule["code"]), metrics
                )

                cur.execute(
                    "insert into rule_evaluation (tenant_id, rule_id, run_id,"
                    " entity_type, entity_id, data_through, matched,"
                    " metrics_snapshot, proposed_action, reason_text, blocked_by)"
                    " values (%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s) returning id",
                    (
                        tenant_id,
                        rule["id"],
                        run_id,
                        rule["scope"],
                        key[1],
                        through,
                        json.dumps(metrics, default=str),
                        json.dumps(
                            {"type": action_type, "value": decision.value},
                            default=str,
                        ),
                        reason,
                        decision.blocked_by.value if decision.blocked_by else None,
                    ),
                )
                evaluation_id = cur.fetchone()["id"]

                if not decision.allowed:
                    s.block(decision.blocked_by)
                    continue

                # Always queued as pending. Dry-run proposals are reviewable but
                # can never be applied; that check lives in services/actions.
                # Diagnostics are pending too: pending means "unread" for them,
                # and 0006 forbids them from ever reaching 'applied'.
                cur.execute(
                    "insert into action (tenant_id, rule_id, evaluation_id,"
                    " entity_type, entity_id, action_type, before_value,"
                    " after_value, reason_text, clamped, clamp_note,"
                    " idempotency_key) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    " on conflict (tenant_id, idempotency_key) do nothing",
                    (
                        tenant_id,
                        rule["id"],
                        evaluation_id,
                        rule["scope"],
                        key[1],
                        action_type,
                        json.dumps({"value": current}),
                        json.dumps(
                            {"value": decision.value, "diagnostic": True}
                            if diagnostic
                            else {"value": decision.value}
                        ),
                        reason,
                        decision.clamped,
                        "; ".join(decision.notes) or None,
                        f"{run_id}:{rule['code']}:{key[1]}",
                    ),
                )
                if diagnostic:
                    s.flagged += 1
                else:
                    claimed.add(key)
                    s.proposed += 1

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
        conn.commit()

    return s
