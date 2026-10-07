"""Search-term isolation negatives and historical-winner revive (R07.4).

Two independent, proposal-only recommendation families:

``isolation_negative``
    Once a harvested term is live in its exact destination, the source ad
    group keeps matching the same query and competes with it. Recommend a
    negative exact in the source ad group, but only after the destination is
    proven: enabled and receiving traffic since the promotion was applied.
    Isolating earlier would simply switch the query off (overblocking).

``revive_target``
    A paused keyword that converted under break-even and has been dormant may
    deserve controlled recovery. The proposed bid is its last bid, capped at
    the break-even CPC and kept inside tenant bid bounds; cooldown applies.

Both write only to ``search_term_lifecycle_recommendation``. Nothing is queued
in ``action`` and nothing is sent to Amazon.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from services.rules.freshness import SourceFreshness, resolve_source_freshness
from services.rules.guardrails import TenantGuardConfig
from services.rules.harvest import normalize_term
from services.rules.protections import active_protection
from services.rules.settings import load_tenant_guard_config

ISOLATION = "isolation_negative"
REVIVE = "revive_target"
RECOMMENDED = "recommended"
BLOCKED = "blocked"

# isolation
UNSUPPORTED_MATCH_TYPE = "unsupported_match_type"
SAME_AD_GROUP = "same_ad_group"
DUPLICATE = "duplicate"
ALREADY_NEGATIVE = "already_negative"
PROTECTED = "protected"
DESTINATION_MISSING = "destination_missing"
DESTINATION_INACTIVE = "destination_inactive"
DESTINATION_NO_TRAFFIC = "destination_no_traffic"
SOURCE_NO_TRAFFIC = "source_no_traffic"
# revive
RECENT_TRAFFIC = "recent_traffic"
THIN_HISTORY = "thin_history"
ECONOMICS_UNKNOWN = "economics_unknown"
POOR_HISTORY = "poor_history"
BID_UNKNOWN = "bid_unknown"
BOUNDS = "bounds"
COOLDOWN = "cooldown"

OPEN_STATUSES = ("pending", "approved")


@dataclass(frozen=True)
class Thresholds:
    min_destination_impressions: int = 100
    min_destination_clicks: int = 5
    history_days: int = 180
    dormant_days: int = 14
    revive_min_clicks: int = 20
    revive_min_orders: int = 3
    revive_max_acos_ratio: float = 1.0


DEFAULT_THRESHOLDS = Thresholds()


@dataclass
class Finding:
    recommendation_type: str
    subject_key: str
    campaign_id: str
    ad_group_id: str
    term: str
    match_type: str
    keyword_id: str | None = None
    decision: str = RECOMMENDED
    blocked_reason: str | None = None
    lineage_id: str | None = None
    protection_id: str | None = None
    current_bid: float | None = None
    proposed_bid: float | None = None
    evidence: dict = field(default_factory=dict)

    def block(self, reason: str, note: str) -> Finding:
        self.decision, self.blocked_reason = BLOCKED, reason
        self.evidence["note"] = note
        return self


def _f(value) -> float:
    return float(value or 0)


def _plain(row: Mapping) -> dict:
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}


def decide_isolation(
    lineage: Mapping,
    *,
    destination: Mapping | None,
    source: Mapping,
    protection_id: str | None,
    pending_negative: str | None,
    seen: set[str],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Finding:
    """Negative exact for the source ad group once the destination is proven."""
    term = lineage["normalized_term"]
    key = f"{lineage['source_campaign_id']}|{lineage['source_ad_group_id']}|{term}"
    f = Finding(
        ISOLATION,
        f"{key}|{lineage['id']}",
        lineage["source_campaign_id"],
        lineage["source_ad_group_id"],
        term,
        "negative_exact",
        lineage_id=str(lineage["id"]),
        evidence={
            "lineage": {
                "id": str(lineage["id"]),
                "action_id": str(lineage["action_id"]),
                "route_code": lineage["route_code"],
                "applied_at": lineage["applied_at"],
                "destination_campaign_id": lineage["destination_campaign_id"],
                "destination_ad_group_id": lineage["destination_ad_group_id"],
                "destination_match_type": lineage["destination_match_type"],
            },
            "destination": _plain(destination) if destination else None,
            "source_since_applied": _plain(source),
        },
    )
    first = key not in seen
    seen.add(key)
    if lineage["destination_match_type"] != "exact":
        return f.block(UNSUPPORTED_MATCH_TYPE, "only exact promotions can be isolated")
    if lineage["source_ad_group_id"] == lineage["destination_ad_group_id"]:
        return f.block(SAME_AD_GROUP, "a negative here would block the destination itself")
    if not first:
        return f.block(DUPLICATE, "an earlier promotion of this term covers the same source")
    if pending_negative:
        return f.block(DUPLICATE, f"negative already queued by action {pending_negative}")
    if source.get("already_negative"):
        return f.block(ALREADY_NEGATIVE, "term is already negative in the source ad group")
    if protection_id:
        f.protection_id = protection_id
        return f.block(PROTECTED, f"protection {protection_id} forbids negating this term")
    if destination is None:
        return f.block(DESTINATION_MISSING, "destination target not seen in keyword data yet")
    if str(destination.get("status") or "").lower() != "enabled":
        return f.block(
            DESTINATION_INACTIVE, f"destination status is {destination.get('status')!r}"
        )
    if (
        _f(destination.get("impressions")) < thresholds.min_destination_impressions
        or _f(destination.get("clicks")) < thresholds.min_destination_clicks
    ):
        return f.block(
            DESTINATION_NO_TRAFFIC,
            f"destination has {destination.get('impressions') or 0} impressions / "
            f"{destination.get('clicks') or 0} clicks since applied; isolating now would "
            "switch the query off",
        )
    if _f(source.get("clicks")) <= 0:
        return f.block(SOURCE_NO_TRAFFIC, "source no longer competes for this query")
    f.evidence["note"] = (
        f"destination {lineage['destination_ad_group_id']} serves '{term}'; source "
        f"{lineage['source_ad_group_id']} still took {int(_f(source.get('clicks')))} clicks"
    )
    return f


def decide_revive(
    kw: Mapping,
    *,
    enabled_siblings: Iterable[str],
    open_action: str | None,
    last_applied_at: dt.datetime | None,
    cfg: TenantGuardConfig,
    now: dt.datetime,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Finding:
    """Re-enable a dormant historical winner at a bounded, break-even-safe bid."""
    clicks, orders = _f(kw.get("clicks")), _f(kw.get("orders"))
    cost, sales = _f(kw.get("cost")), _f(kw.get("sales"))
    be = kw.get("break_even_acos")
    be = float(be) if be is not None else None
    acos = cost / sales if sales > 0 else None
    bid = kw.get("last_bid")
    bid = float(bid) if bid is not None else None
    siblings = sorted(enabled_siblings)
    f = Finding(
        REVIVE,
        str(kw["keyword_id"]),
        kw["campaign_id"],
        kw["ad_group_id"],
        normalize_term(kw.get("keyword_text") or ""),
        str(kw.get("match_type") or "").lower(),
        keyword_id=str(kw["keyword_id"]),
        current_bid=bid,
        evidence={
            "history": {
                "clicks": clicks, "orders": orders, "cost": cost, "sales": sales,
                "acos": acos, "break_even_acos": be,
                "last_click_date": kw.get("last_click_date"),
                "recent_clicks": _f(kw.get("recent_clicks")),
            },
            "last_bid": bid,
            "bounds": {"min_bid": cfg.min_bid, "max_bid": cfg.max_bid},
            "cooldown_days": cfg.cooldown_days,
            "last_applied_at": last_applied_at,
            "enabled_siblings": siblings,
        },
    )
    if siblings:
        return f.block(DUPLICATE, f"enabled target {siblings[0]} already serves this term")
    if open_action:
        return f.block(DUPLICATE, f"action {open_action} is already open for this keyword")
    if _f(kw.get("recent_clicks")) > 0:
        return f.block(RECENT_TRAFFIC, f"traffic in the last {thresholds.dormant_days}d")
    if clicks < thresholds.revive_min_clicks:
        return f.block(THIN_HISTORY, f"only {int(clicks)} historical clicks")
    if be is None:
        return f.block(ECONOMICS_UNKNOWN, "break-even ACoS unknown")
    if orders < thresholds.revive_min_orders or acos is None or (
        acos > be * thresholds.revive_max_acos_ratio
    ):
        return f.block(
            POOR_HISTORY,
            f"{int(orders)} orders, ACoS {acos if acos is None else round(acos, 4)} "
            f"vs break-even {be}",
        )
    if bid is None or bid <= 0:
        return f.block(BID_UNKNOWN, "no historical bid to revive at")
    if last_applied_at is not None and (now - last_applied_at).days < cfg.cooldown_days:
        return f.block(
            COOLDOWN,
            f"changed {(now - last_applied_at).days}d ago, cooldown is {cfg.cooldown_days}d",
        )
    break_even_cpc = sales / clicks * be
    target = min(bid, break_even_cpc)
    f.evidence["break_even_cpc"] = round(break_even_cpc, 4)
    if target < cfg.min_bid:
        return f.block(
            BOUNDS, f"break-even CPC {break_even_cpc:.2f} is below min_bid {cfg.min_bid}"
        )
    f.proposed_bid = round(min(target, cfg.max_bid), 2)
    f.evidence["note"] = (
        f"{int(orders)} orders at ACoS {acos:.2%} (break-even {be:.2%}); revive at "
        f"{f.proposed_bid}"
    )
    return f


ISOLATION_LINEAGE_SQL = """
select l.id, l.action_id, l.route_code, l.normalized_term, l.source_campaign_id,
       l.source_ad_group_id, l.destination_campaign_id, l.destination_ad_group_id,
       l.destination_match_type, a.applied_at
  from search_term_harvest_lineage l
  join action a on a.id = l.action_id and a.tenant_id = l.tenant_id
 where l.tenant_id = %s and a.status in ('applied','verified') and a.applied_at is not null
 order by a.applied_at, l.created_at, l.id
"""

# Marts have no RLS: the tenant predicate is the isolation boundary.
DESTINATION_SQL = """
select keyword_id,
       (array_agg(keyword_status order by report_date desc))[1] as status,
       coalesce(sum(impressions) filter (where report_date > %(applied)s), 0) as impressions,
       coalesce(sum(clicks) filter (where report_date > %(applied)s), 0) as clicks,
       coalesce(sum(cost) filter (where report_date > %(applied)s), 0) as cost,
       coalesce(sum(attributed_orders_7d) filter (where report_date > %(applied)s), 0) as orders
  from marts.mart_ppc_keyword_daily
 where tenant_id = %(tenant)s and campaign_id = %(campaign)s and ad_group_id = %(ad_group)s
   and lower(match_type) = 'exact'
   and regexp_replace(lower(btrim(keyword_text)), '\\s+', ' ', 'g') = %(term)s
   and report_date <= %(through)s and is_settled
 group by keyword_id
 order by keyword_id
 limit 1
"""

SOURCE_SQL = """
select coalesce(sum(clicks) filter (where report_date > %(applied)s), 0) as clicks,
       coalesce(sum(cost) filter (where report_date > %(applied)s), 0) as cost,
       coalesce(sum(attributed_orders_7d) filter (where report_date > %(applied)s), 0) as orders,
       coalesce(bool_or(is_already_negative), false) as already_negative
  from marts.mart_ppc_search_term_daily
 where tenant_id = %(tenant)s and campaign_id = %(campaign)s and ad_group_id = %(ad_group)s
   and regexp_replace(lower(btrim(search_term)), '\\s+', ' ', 'g') = %(term)s
   and report_date <= %(through)s and is_settled
"""

REVIVE_SQL = """
with kw as (
  select * from marts.mart_ppc_keyword_daily
   where tenant_id = %(tenant)s and is_settled
     and report_date > %(through)s - %(history)s * interval '1 day'
     and report_date <= %(through)s
), latest as (
  select distinct on (keyword_id) keyword_id, campaign_id, ad_group_id, keyword_text,
         match_type, keyword_status
    from kw order by keyword_id, report_date desc
)
select l.*, a.clicks, a.impressions, a.cost, a.orders, a.sales, a.break_even_acos,
       a.last_bid, a.last_click_date, a.recent_clicks
  from latest l
  join (
    select keyword_id, sum(clicks) clicks, sum(impressions) impressions, sum(cost) cost,
           sum(attributed_orders_7d) orders, sum(attributed_sales_7d) sales,
           min(break_even_acos) break_even_acos,
           (array_agg(bid order by report_date desc) filter (where bid is not null))[1] last_bid,
           max(report_date) filter (where clicks > 0) last_click_date,
           coalesce(sum(clicks) filter (
             where report_date > %(through)s - %(dormant)s * interval '1 day'), 0) recent_clicks
      from kw group by keyword_id
  ) a using (keyword_id)
 order by keyword_id
"""


def _protection(cur, tenant_id: str, term: str, now: dt.datetime) -> str | None:
    for entity_type in ("search_term", "keyword"):
        p = active_protection(
            cur,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_value=term,
            action_type="add_negative_exact",
            now=now,
        )
        if p.blocked:
            return p.protection_id
    return None


def _open_action(cur, tenant_id: str, entity_type: str, entity_id: str, action_types) -> str | None:
    cur.execute(
        """select id from action
            where tenant_id = %s and entity_type = %s and lower(btrim(entity_id)) = %s
              and action_type = any(%s) and status = any(%s)
            order by requested_at, id limit 1""",
        (tenant_id, entity_type, entity_id.lower(), list(action_types), list(OPEN_STATUSES)),
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


def isolation_findings(cur, *, tenant_id: str, through: dt.date, now: dt.datetime,
                       thresholds: Thresholds) -> list[Finding]:
    cur.execute(ISOLATION_LINEAGE_SQL, (tenant_id,))
    seen: set[str] = set()
    findings = []
    for lin in cur.fetchall():
        applied = lin["applied_at"].date()
        term = lin["normalized_term"]
        cur.execute(DESTINATION_SQL, {
            "tenant": tenant_id, "campaign": lin["destination_campaign_id"],
            "ad_group": lin["destination_ad_group_id"], "term": term,
            "applied": applied, "through": through,
        })
        destination = cur.fetchone()
        cur.execute(SOURCE_SQL, {
            "tenant": tenant_id, "campaign": lin["source_campaign_id"],
            "ad_group": lin["source_ad_group_id"], "term": term,
            "applied": applied, "through": through,
        })
        source = cur.fetchone()
        findings.append(decide_isolation(
            lin,
            destination=destination,
            source=source,
            protection_id=_protection(cur, tenant_id, term, now),
            pending_negative=_open_action(cur, tenant_id, "search_term", term,
                                          ("add_negative_exact",)),
            seen=seen,
            thresholds=thresholds,
        ))
    return findings


def revive_findings(cur, *, tenant_id: str, through: dt.date, now: dt.datetime,
                    cfg: TenantGuardConfig, thresholds: Thresholds) -> list[Finding]:
    cur.execute(REVIVE_SQL, {
        "tenant": tenant_id, "through": through,
        "history": thresholds.history_days, "dormant": thresholds.dormant_days,
    })
    rows = cur.fetchall()
    enabled: dict[tuple, list[str]] = {}
    for r in rows:
        if str(r["keyword_status"] or "").lower() == "enabled":
            k = (r["ad_group_id"], normalize_term(r["keyword_text"] or ""),
                 str(r["match_type"] or "").lower())
            enabled.setdefault(k, []).append(str(r["keyword_id"]))
    findings = []
    for r in rows:
        if str(r["keyword_status"] or "").lower() != "paused":
            continue
        k = (r["ad_group_id"], normalize_term(r["keyword_text"] or ""),
             str(r["match_type"] or "").lower())
        cur.execute(
            "select last_applied_at from v_last_applied_action"
            " where tenant_id = %s and entity_type = 'keyword' and entity_id = %s",
            (tenant_id, str(r["keyword_id"])),
        )
        last = cur.fetchone()
        findings.append(decide_revive(
            r,
            enabled_siblings=enabled.get(k, ()),
            open_action=_open_action(cur, tenant_id, "keyword", str(r["keyword_id"]),
                                     ("enable", "set_bid")),
            last_applied_at=last["last_applied_at"] if last else None,
            cfg=cfg,
            now=now,
            thresholds=thresholds,
        ))
    return findings


@dataclass
class LifecycleRun:
    run_id: str
    tenant_id: str
    status: dict = field(default_factory=dict)
    data_through: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)


def _fresh(cur, tenant_id, scope, now, cfg) -> SourceFreshness:
    return resolve_source_freshness(
        cur,
        tenant_id=tenant_id,
        scope=scope,
        now=now,
        settled_cutoff=now.date() - dt.timedelta(days=cfg.settlement_lag_days),
        max_age_hours=cfg.max_data_age_hours,
    )


def _insert(cur, tenant_id, run_id, f: Finding, thresholds: Thresholds, through: dt.date):
    cur.execute(
        """insert into search_term_lifecycle_recommendation(
             tenant_id, run_id, recommendation_type, decision, blocked_reason, subject_key,
             campaign_id, ad_group_id, keyword_id, term, match_type, lineage_id,
             protection_id, current_bid, proposed_bid, evidence, thresholds, data_through)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            tenant_id, run_id, f.recommendation_type, f.decision, f.blocked_reason,
            f.subject_key, f.campaign_id, f.ad_group_id, f.keyword_id, f.term, f.match_type,
            f.lineage_id, f.protection_id, f.current_bid, f.proposed_bid,
            json.dumps(f.evidence, default=str), json.dumps(asdict(thresholds)), through,
        ),
    )


def run_analysis(
    conn: psycopg.Connection,
    tenant_id: str,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    now: dt.datetime | None = None,
) -> LifecycleRun:
    """Write both recommendation families; each is gated on its own freshness."""
    now = now or dt.datetime.now(dt.timezone.utc)
    result = LifecycleRun(run_id=str(uuid.uuid4()), tenant_id=tenant_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cfg = load_tenant_guard_config(cur, tenant_id)
        keyword = _fresh(cur, tenant_id, "keyword", now, cfg)
        search_term = _fresh(cur, tenant_id, "search_term", now, cfg)

        families = []
        if not keyword.usable:
            result.status[ISOLATION] = result.status[REVIVE] = keyword.block_reason
        else:
            families.append((REVIVE, keyword.data_through))
            if not search_term.usable:
                result.status[ISOLATION] = search_term.block_reason
            else:
                families.append(
                    (ISOLATION, min(keyword.data_through, search_term.data_through))
                )
        for family, through in families:
            if family == ISOLATION:
                findings = isolation_findings(
                    cur, tenant_id=tenant_id, through=through, now=now, thresholds=thresholds
                )
            else:
                findings = revive_findings(
                    cur, tenant_id=tenant_id, through=through, now=now, cfg=cfg,
                    thresholds=thresholds,
                )
            result.status[family] = "success"
            result.data_through[family] = through
            for f in findings:
                label = f"{family}:{f.blocked_reason or f.decision}"
                result.decisions[label] = result.decisions.get(label, 0) + 1
                _insert(cur, tenant_id, result.run_id, f, thresholds, through)
    conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolation and revive recommendations")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    url = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
    with psycopg.connect(url) as conn:
        print(asdict(run_analysis(conn, args.tenant_id)))


if __name__ == "__main__":
    main()
