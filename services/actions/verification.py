"""T+7 action verification and scorecard.

Reads applied actions whose verification window has matured, compares post-action
performance with the pre-action baseline window, and marks the action verified
with an operator-readable outcome.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from services.actions import state_machine as sm

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
WINDOW_DAYS = 7


@dataclass(frozen=True)
class MetricWindow:
    cost: float
    sales: float
    clicks: int
    orders: int

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


@dataclass
class VerificationResult:
    scanned: int = 0
    verified: int = 0
    inconclusive: int = 0
    worsened: int = 0


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
    )


def fetch_due_actions(conn, tenant_id: str, now: dt.datetime, limit: int) -> list[sm.Action]:
    rows = conn.execute(
        """
        select id, tenant_id, entity_type, entity_id, action_type, before_value,
               after_value, status, applied_at
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


def keyword_window(conn, tenant_id: str, keyword_id: str, start: dt.date, end: dt.date) -> MetricWindow:
    row = conn.execute(
        """
        select coalesce(sum(cost), 0) as cost,
               coalesce(sum(attributed_sales_7d), 0) as sales,
               coalesce(sum(clicks), 0) as clicks,
               coalesce(sum(attributed_orders_7d), 0) as orders
          from marts.mart_ppc_keyword_daily
         where tenant_id = %s
           and keyword_id = %s
           and is_settled
           and report_date >= %s
           and report_date < %s
        """,
        (tenant_id, keyword_id, start, end),
    ).fetchone()
    return MetricWindow(float(row["cost"]), float(row["sales"]), int(row["clicks"]), int(row["orders"]))


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


def verify_action(conn, action: sm.Action, *, now: dt.datetime) -> sm.Action:
    assert action.applied_at is not None
    applied_date = action.applied_at.date()
    before = keyword_window(
        conn,
        action.tenant_id,
        action.entity_id,
        applied_date - dt.timedelta(days=WINDOW_DAYS),
        applied_date,
    )
    after = keyword_window(
        conn,
        action.tenant_id,
        action.entity_id,
        applied_date,
        applied_date + dt.timedelta(days=WINDOW_DAYS),
    )
    outcome, impact = judge(before, after)
    updated = sm.verify(action, now=now, outcome=outcome, impact=impact)
    conn.execute(
        """
        update action
           set status = %s, verified_at = %s, outcome = %s, impact_jsonb = %s
         where tenant_id = %s and id = %s
        """,
        (updated.status.value, updated.verified_at, updated.outcome, psycopg.types.json.Jsonb(impact), updated.tenant_id, updated.id),
    )
    return updated


def run_once(tenant_id: str, *, limit: int = 50, database_url: str = DATABASE_URL, now: dt.datetime | None = None) -> VerificationResult:
    now = now or dt.datetime.now(dt.timezone.utc)
    result = VerificationResult()
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        actions = fetch_due_actions(conn, tenant_id, now, limit)
        result.scanned = len(actions)
        for action in actions:
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
        f"inconclusive={result.inconclusive} worsened={result.worsened}"
    )


if __name__ == "__main__":
    main()
