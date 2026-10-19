"""Idempotent multi-horizon action verification and legacy T+7 scorecard."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from services.actions import state_machine as sm
from services.actions.audit import EventType, append_event, event_for

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
WINDOW_DAYS = 7
HORIZONS = (1, 3, 7, 14, 30)
ACTION_METRICS = {
    "set_bid": ("cost", "sales", "clicks", "orders", "acos", "cvr", "cpc"),
    "set_budget": ("cost", "sales", "orders", "acos"),
    "set_placement_modifier": ("cost", "sales", "clicks", "orders", "acos", "cvr"),
    "pause": ("cost", "sales", "orders"),
    "enable": ("cost", "sales", "orders"),
    "create_keyword": ("cost", "sales", "clicks", "orders", "acos", "cvr"),
    "add_negative_exact": ("cost", "sales", "clicks", "orders"),
    "add_negative_phrase": ("cost", "sales", "clicks", "orders"),
}


@dataclass(frozen=True)
class MetricWindow:
    cost: float
    sales: float
    clicks: int
    orders: int
    observed_days: int = 0
    data_through: dt.date | None = None

    @property
    def acos(self) -> float | None:
        if self.sales <= 0:
            return None
        return self.cost / self.sales

    @property
    def cvr(self) -> float | None:
        if self.clicks <= 0:
            return None
        return self.orders / self.clicks

    @property
    def cpc(self) -> float | None:
        return self.cost / self.clicks if self.clicks > 0 else None

    def metrics(self) -> dict:
        return {"cost": self.cost, "sales": self.sales, "clicks": self.clicks,
                "orders": self.orders, "acos": self.acos, "cvr": self.cvr,
                "cpc": self.cpc, "observed_days": self.observed_days,
                "data_through": self.data_through.isoformat() if self.data_through else None}


@dataclass
class VerificationResult:
    scanned: int = 0
    verified: int = 0
    inconclusive: int = 0
    worsened: int = 0
    snapshots_complete: int = 0
    insufficient_data: int = 0


def _to_action(row: dict) -> sm.Action:
    return sm.Action(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        action_type=row["action_type"],
        before_value=row["before_value"],
        after_value=row["after_value"],
        status=sm.Status(row["status"]),
        applied_at=row["applied_at"],
        idempotency_key=row["idempotency_key"],
    )


def fetch_due_actions(conn, tenant_id: str, now: dt.datetime, limit: int) -> list[sm.Action]:
    rows = conn.execute(
        """
        select id, tenant_id, entity_type, entity_id, action_type, before_value,
               after_value, status, applied_at, idempotency_key
          from action
         where tenant_id = %s
           and status = 'applied'
           and applied_at <= %s - interval '7 days'
         order by applied_at
         limit %s
        """,
        (tenant_id, now, limit),
    ).fetchall()
    return [_to_action(r) for r in rows]


def _window_from_row(row: dict) -> MetricWindow:
    return MetricWindow(float(row["cost"]), float(row["sales"]), int(row["clicks"]), int(row["orders"]), int(row.get("observed_days") or 0), row.get("data_through"))


def performance_window(conn, action: sm.Action, start: dt.date, end: dt.date) -> MetricWindow:
    if action.entity_type in {"keyword", "target"}:
        return keyword_window(conn, action.tenant_id, action.entity_id, start, end)
    if action.entity_type == "campaign":
        return campaign_window(conn, action.tenant_id, action.entity_id, start, end)
    if action.entity_type == "placement":
        return placement_window(conn, action.tenant_id, action.entity_id, start, end)
    if action.entity_type == "search_term":
        return search_term_window(conn, action.tenant_id, action.entity_id, start, end)
    raise ValueError(f"verification not wired for entity_type={action.entity_type!r}")


def keyword_window(conn, tenant_id: str, keyword_id: str, start: dt.date, end: dt.date) -> MetricWindow:
    row = conn.execute(
        """
        select coalesce(sum(cost), 0) as cost,
               coalesce(sum(attributed_sales_7d), 0) as sales,
               coalesce(sum(clicks), 0) as clicks,
               coalesce(sum(attributed_orders_7d), 0) as orders,
               count(distinct report_date) as observed_days,
               max(report_date) as data_through
          from marts.mart_ppc_keyword_daily
         where tenant_id = %s
           and keyword_id = %s
           and is_settled
           and report_date >= %s
           and report_date < %s
        """,
        (tenant_id, keyword_id, start, end),
    ).fetchone()
    return _window_from_row(row)


def campaign_window(conn, tenant_id: str, campaign_id: str, start: dt.date, end: dt.date) -> MetricWindow:
    row = conn.execute(
        """
        select coalesce(sum(cost), 0) as cost,
               coalesce(sum(attributed_sales_7d), 0) as sales,
               coalesce(sum(clicks), 0) as clicks,
               coalesce(sum(attributed_orders_7d), 0) as orders,
               count(distinct report_date) as observed_days,
               max(report_date) as data_through
          from marts.mart_ppc_campaign_daily
         where tenant_id = %s
           and campaign_id = %s
           and is_settled
           and report_date >= %s
           and report_date < %s
        """,
        (tenant_id, campaign_id, start, end),
    ).fetchone()
    return _window_from_row(row)


def placement_window(conn, tenant_id: str, entity_id: str, start: dt.date, end: dt.date) -> MetricWindow:
    campaign_id, placement = entity_id.split(":", 1)
    row = conn.execute(
        """
        select coalesce(sum(cost), 0) as cost,
               coalesce(sum(attributed_sales_7d), 0) as sales,
               coalesce(sum(clicks), 0) as clicks,
               coalesce(sum(attributed_orders_7d), 0) as orders,
               count(distinct report_date) as observed_days,
               max(report_date) as data_through
          from marts.mart_ppc_placement_daily
         where tenant_id = %s
           and campaign_id = %s
           and placement = %s
           and is_settled
           and report_date >= %s
           and report_date < %s
        """,
        (tenant_id, campaign_id, placement, start, end),
    ).fetchone()
    return _window_from_row(row)


def search_term_window(conn, tenant_id: str, search_term: str, start: dt.date, end: dt.date) -> MetricWindow:
    row = conn.execute(
        """
        select coalesce(sum(cost), 0) as cost,
               coalesce(sum(attributed_sales_7d), 0) as sales,
               coalesce(sum(clicks), 0) as clicks,
               coalesce(sum(attributed_orders_7d), 0) as orders,
               count(distinct report_date) as observed_days,
               max(report_date) as data_through
          from marts.mart_ppc_search_term_daily
         where tenant_id = %s
           and search_term = %s
           and is_settled
           and report_date >= %s
           and report_date < %s
        """,
        (tenant_id, search_term, start, end),
    ).fetchone()
    return _window_from_row(row)


def judge(before: MetricWindow, after: MetricWindow) -> tuple[str, dict]:
    impact = {
        "before": {"cost": before.cost, "sales": before.sales, "clicks": before.clicks, "orders": before.orders, "acos": before.acos, "cvr": before.cvr},
        "after": {"cost": after.cost, "sales": after.sales, "clicks": after.clicks, "orders": after.orders, "acos": after.acos, "cvr": after.cvr},
    }
    if before.clicks < 10 or after.clicks < 10:
        return "inconclusive", impact
    if before.acos is not None and after.acos is not None:
        if after.acos <= before.acos * 0.9:
            return "improved", impact
        if after.acos >= before.acos * 1.1:
            return "worsened", impact
        return "neutral", impact
    if after.orders > before.orders and after.cost <= before.cost * 1.2:
        return "improved", impact
    return "inconclusive", impact


def fetch_due_snapshots(conn, tenant_id: str, now: dt.datetime, limit: int) -> list[tuple[sm.Action, int]]:
    """Return due action/horizon pairs that do not already have final evidence."""
    rows = conn.execute(
        """
        select a.id,a.tenant_id,a.entity_type,a.entity_id,a.action_type,a.before_value,
               a.after_value,a.status,a.applied_at,a.idempotency_key,h.horizon_days
          from action a
          cross join (values (1),(3),(7),(14),(30)) h(horizon_days)
          left join action_verification_snapshot s
            on s.tenant_id=a.tenant_id and s.action_id=a.id
           and s.horizon_days=h.horizon_days and s.status='COMPLETE'
         where a.tenant_id=%s and a.status in ('applied','verified')
           and a.applied_at <= %s - make_interval(days=>h.horizon_days)
           and s.id is null
         order by a.applied_at,h.horizon_days
         limit %s
        """,
        (tenant_id, now, limit),
    ).fetchall()
    return [(_to_action(row), int(row["horizon_days"])) for row in rows]


def _mature(window: MetricWindow, start: dt.date, end: dt.date) -> bool:
    days = (end - start).days
    return days > 0 and window.observed_days >= days and window.data_through is not None and window.data_through >= end - dt.timedelta(days=1)


def verify_horizon(conn, action: sm.Action, horizon_days: int, *, now: dt.datetime) -> str:
    """Persist one reproducible horizon; immature rows remain safely retryable."""
    if horizon_days not in HORIZONS:
        raise ValueError("unsupported verification horizon")
    assert action.applied_at is not None
    applied = action.applied_at.date()
    before_start, before_end = applied - dt.timedelta(days=horizon_days), applied
    after_start, after_end = applied, applied + dt.timedelta(days=horizon_days)
    metric_keys = ACTION_METRICS.get(action.action_type)
    status, outcome, reason = "FAILED", None, "UNSUPPORTED_ACTION_METRICS"
    before = MetricWindow(0, 0, 0, 0)
    after = MetricWindow(0, 0, 0, 0)
    if metric_keys is not None:
        before = performance_window(conn, action, before_start, before_end)
        after = performance_window(conn, action, after_start, after_end)
        if not _mature(before, before_start, before_end) or not _mature(after, after_start, after_end):
            status, reason = "INSUFFICIENT_DATA", "WINDOW_NOT_MATURE"
        else:
            outcome, _ = judge(before, after)
            status, reason = "COMPLETE", None
    selected_before = {key: before.metrics().get(key) for key in metric_keys or ()}
    selected_after = {key: after.metrics().get(key) for key in metric_keys or ()}
    data_through = after.data_through
    conn.execute(
        """
        insert into action_verification_snapshot(
          tenant_id,action_id,horizon_days,status,outcome,metric_keys,
          baseline_metrics,observed_metrics,window_before_start,window_before_end,
          window_after_start,window_after_end,data_through,reason_code,checked_at,completed_at)
        values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               case when %s='COMPLETE' then %s end)
        on conflict(tenant_id,action_id,horizon_days) do update set
          status=excluded.status,outcome=excluded.outcome,metric_keys=excluded.metric_keys,
          baseline_metrics=excluded.baseline_metrics,observed_metrics=excluded.observed_metrics,
          data_through=excluded.data_through,reason_code=excluded.reason_code,
          checked_at=excluded.checked_at,completed_at=excluded.completed_at
        where action_verification_snapshot.status<>'COMPLETE'
        """,
        (action.tenant_id, action.id, horizon_days, status, outcome,
         psycopg.types.json.Jsonb(list(metric_keys or ())), psycopg.types.json.Jsonb(selected_before),
         psycopg.types.json.Jsonb(selected_after), before_start, before_end, after_start, after_end,
         data_through, reason, now, status, now),
    )
    return status


def verify_action(conn, action: sm.Action, *, now: dt.datetime) -> sm.Action:
    assert action.applied_at is not None
    correlation_key = f"verification:{action.id}:{action.applied_at.isoformat()}"
    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_SCHEDULED,
            correlation_key=correlation_key,
            dedupe_key="verification:scheduled",
            actor_type="system",
            actor_id="verification-worker",
            previous_state=action.status.value,
            new_state=action.status.value,
        ),
    )
    applied_date = action.applied_at.date()
    before = performance_window(
        conn,
        action,
        applied_date - dt.timedelta(days=WINDOW_DAYS),
        applied_date,
    )
    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_CHECKPOINT,
            correlation_key=correlation_key,
            dedupe_key="verification:before-window",
            actor_type="system",
            actor_id="verification-worker",
            verification_checkpoint="before_window_loaded",
            metadata={"window": before.__dict__},
        ),
    )
    after = performance_window(
        conn,
        action,
        applied_date,
        applied_date + dt.timedelta(days=WINDOW_DAYS),
    )
    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_CHECKPOINT,
            correlation_key=correlation_key,
            dedupe_key="verification:after-window",
            actor_type="system",
            actor_id="verification-worker",
            verification_checkpoint="after_window_loaded",
            metadata={"window": after.__dict__},
        ),
    )
    outcome, impact = judge(before, after)
    impact["entity_type"] = action.entity_type
    updated = sm.verify(action, now=now, outcome=outcome, impact=impact)
    conn.execute(
        """
        update action
           set status = %s, verified_at = %s, outcome = %s, impact_jsonb = %s
         where tenant_id = %s and id = %s
        """,
        (updated.status.value, updated.verified_at, updated.outcome, psycopg.types.json.Jsonb(impact), updated.tenant_id, updated.id),
    )
    for kind, suffix in (
        (EventType.VERIFICATION_RESULT, "result"),
        (EventType.VERIFICATION_TERMINAL, "terminal"),
    ):
        append_event(
            conn,
            event_for(
                updated,
                kind,
                correlation_key=correlation_key,
                dedupe_key=f"verification:{suffix}",
                actor_type="system",
                actor_id="verification-worker",
                previous_state=sm.Status.APPLIED.value,
                new_state=updated.status.value,
                provider_result_classification=outcome,
                verification_checkpoint=outcome,
                metadata={"impact": impact},
            ),
        )
    return updated


def run_once(tenant_id: str, *, limit: int = 50, database_url: str = DATABASE_URL, now: dt.datetime | None = None) -> VerificationResult:
    now = now or dt.datetime.now(dt.timezone.utc)
    result = VerificationResult()
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        due = fetch_due_snapshots(conn, tenant_id, now, limit)
        result.scanned = len(due)
        for action, horizon in due:
            status = verify_horizon(conn, action, horizon, now=now)
            if status == "INSUFFICIENT_DATA":
                result.insufficient_data += 1
                continue
            if status != "COMPLETE":
                continue
            result.snapshots_complete += 1
            # Preserve the original action-level T+7 scorecard contract. Later
            # horizons enrich evidence without re-opening the action lifecycle.
            if horizon == WINDOW_DAYS and action.status is sm.Status.APPLIED:
                updated = verify_action(conn, action, now=now)
                result.verified += 1
                if updated.outcome == "inconclusive":
                    result.inconclusive += 1
                if updated.outcome == "worsened":
                    result.worsened += 1
        conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify mature applied actions")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    result = run_once(args.tenant_id, limit=args.limit)
    print(
        f"actions scanned={result.scanned} verified={result.verified} "
        f"inconclusive={result.inconclusive} worsened={result.worsened} "
        f"snapshots_complete={result.snapshots_complete} "
        f"insufficient_data={result.insufficient_data}"
    )


if __name__ == "__main__":
    main()
