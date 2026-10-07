"""Deterministic search-term harvest routing and promotion lineage.

A harvest proposal must answer three questions before it reaches the approval
queue: where did the term come from, where will it go, and why there. Every
answer is recorded so a promotion can be traced end to end, and every
ambiguity (no route, competing routes, an existing target) fails closed.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass

WILDCARD = "*"
ASIN_TERM = re.compile(r"^b0[0-9a-z]{8}$")
OPEN_ACTION_STATUSES = ("pending", "approved", "applied", "verified")
FUNNEL_BY_BRAND_CLASS = {
    "own_brand": "brand_defense",
    "competitor": "conquest",
    "generic": "performance",
}
_BRAND_CLASS_ORDER = {"own_brand": 0, "competitor": 1}

DUPLICATE_TARGET = "duplicate_target"
ROUTE_MISSING = "harvest_route_missing"
ROUTE_CONFLICT = "harvest_route_conflict"


def normalize_term(term: str) -> str:
    return " ".join(str(term).lower().split())


def destination_match_type(term: str) -> str:
    """ASIN search terms become product targets; everything else exact keywords."""
    return "product" if ASIN_TERM.match(normalize_term(term)) else "exact"


def classify_brand(term: str, brand_terms: Iterable[tuple[str, str]]) -> tuple[str, str | None]:
    """Return (brand_class, matched_term) using whole-word containment.

    The longest matching brand term wins; own brand beats competitor on a tie.
    """
    padded = f" {normalize_term(term)} "
    hits = [
        (normalize_term(bt), cls)
        for bt, cls in brand_terms
        if normalize_term(bt) and f" {normalize_term(bt)} " in padded
    ]
    if not hits:
        return "generic", None
    best = min(hits, key=lambda h: (-len(h[0]), _BRAND_CLASS_ORDER.get(h[1], 9), h[0]))
    return best[1], best[0]


@dataclass(frozen=True)
class Source:
    campaign_id: str
    ad_group_id: str
    keyword_id: str | None
    match_type: str | None
    advertised_asin: str | None
    orders: int
    sales: float
    clicks: int


def choose_source(rows: Sequence[Mapping]) -> Source | None:
    """Pick the source ad group that earned the promotion, deterministically."""
    sources = [
        Source(
            campaign_id=str(r["campaign_id"]),
            ad_group_id=str(r["ad_group_id"]),
            keyword_id=None if r.get("matched_keyword_id") is None else str(r["matched_keyword_id"]),
            match_type=r.get("matched_match_type"),
            advertised_asin=r.get("advertised_asin"),
            orders=int(r.get("orders") or 0),
            sales=float(r.get("sales") or 0),
            clicks=int(r.get("clicks") or 0),
        )
        for r in rows
        if r.get("campaign_id") is not None and r.get("ad_group_id") is not None
    ]
    if not sources:
        return None
    return min(
        sources,
        key=lambda s: (-s.orders, -s.sales, -s.clicks, s.campaign_id, s.ad_group_id,
                       s.keyword_id or ""),
    )


@dataclass(frozen=True)
class Route:
    id: str
    code: str
    priority: int
    asin: str
    brand_class: str
    match_type: str
    strategy_code: str
    funnel_purpose: str
    destination_campaign_id: str
    destination_ad_group_id: str

    @property
    def specificity(self) -> int:
        return sum(v != WILDCARD for v in (self.asin, self.brand_class, self.strategy_code))

    @property
    def destination(self) -> tuple[str, str]:
        return (self.destination_campaign_id, self.destination_ad_group_id)


@dataclass(frozen=True)
class Candidate:
    search_term: str
    normalized_term: str
    asin: str | None
    brand_class: str
    brand_term: str | None
    match_type: str
    funnel_purpose: str
    strategy_codes: frozenset[str]


def build_candidate(
    search_term: str,
    *,
    asin: str | None,
    brand_terms: Iterable[tuple[str, str]],
    strategy_codes: Iterable[str],
) -> Candidate:
    brand_class, brand_term = classify_brand(search_term, brand_terms)
    return Candidate(
        search_term=search_term,
        normalized_term=normalize_term(search_term),
        asin=asin.upper() if asin else None,
        brand_class=brand_class,
        brand_term=brand_term,
        match_type=destination_match_type(search_term),
        funnel_purpose=FUNNEL_BY_BRAND_CLASS[brand_class],
        strategy_codes=frozenset(strategy_codes),
    )


def _eligible(route: Route, c: Candidate) -> bool:
    return (
        route.match_type == c.match_type
        and route.funnel_purpose == c.funnel_purpose
        and route.asin in (WILDCARD, c.asin)
        and route.brand_class in (WILDCARD, c.brand_class)
        and (route.strategy_code == WILDCARD or route.strategy_code in c.strategy_codes)
    )


@dataclass(frozen=True)
class RouteDecision:
    route: Route | None
    blocked_by: str | None
    reason: str
    considered: tuple[str, ...]


def select_route(candidate: Candidate, routes: Iterable[Route]) -> RouteDecision:
    """Most specific eligible route wins, then lowest priority number.

    Two top-ranked routes pointing at different destinations are a conflict and
    block the promotion instead of guessing.
    """
    eligible = sorted(
        (r for r in routes if _eligible(r, candidate)),
        key=lambda r: (-r.specificity, r.priority, r.code, r.id),
    )
    considered = tuple(r.code for r in eligible)
    if not eligible:
        return RouteDecision(
            None,
            ROUTE_MISSING,
            f"no enabled {candidate.match_type} route for {candidate.brand_class} "
            f"term (funnel {candidate.funnel_purpose}, asin {candidate.asin or 'unknown'})",
            considered,
        )
    best = eligible[0]
    top = [r for r in eligible if (r.specificity, r.priority) == (best.specificity, best.priority)]
    destinations = sorted({r.destination for r in top})
    if len(destinations) > 1:
        return RouteDecision(
            None,
            ROUTE_CONFLICT,
            "competing destinations at specificity "
            f"{best.specificity}/priority {best.priority}: "
            + ", ".join(sorted(r.code for r in top)),
            considered,
        )
    return RouteDecision(
        best,
        None,
        f"route {best.code} sends {candidate.brand_class} term to {best.match_type} in "
        f"campaign {best.destination_campaign_id} / ad group {best.destination_ad_group_id} "
        f"(funnel {best.funnel_purpose}; asin={best.asin}, brand_class={best.brand_class}, "
        f"strategy={best.strategy_code}; specificity {best.specificity}, "
        f"priority {best.priority})",
        considered,
    )


@dataclass
class HarvestPlan:
    blocked_by: str | None
    note: str
    candidate: Candidate | None = None
    source: Source | None = None
    route: Route | None = None

    @property
    def routing_reason(self) -> str:
        return self.note

    @property
    def destination(self) -> dict | None:
        if self.route is None or self.candidate is None:
            return None
        return {
            "campaign_id": self.route.destination_campaign_id,
            "ad_group_id": self.route.destination_ad_group_id,
            "match_type": self.candidate.match_type,
            "route_code": self.route.code,
        }

    def evidence(self) -> dict:
        candidate = None
        if self.candidate is not None:
            candidate = asdict(self.candidate)
            candidate["strategy_codes"] = sorted(self.candidate.strategy_codes)
        return {
            "version": 1,
            "blocked_by": self.blocked_by,
            "routing_reason": self.note,
            "candidate": candidate,
            "source": asdict(self.source) if self.source else None,
            "route": asdict(self.route) if self.route else None,
            "destination": self.destination,
        }


def _fetch_sources(cur, tenant_id: str, term: str, lookback_days: int, through: dt.date):
    cur.execute(
        """select campaign_id, ad_group_id, matched_keyword_id, matched_match_type,
                  max(advertised_asin) as advertised_asin,
                  sum(attributed_orders_7d) as orders,
                  sum(attributed_sales_7d) as sales,
                  sum(clicks) as clicks
             from marts.mart_ppc_search_term_daily
            where tenant_id = %s
              and lower(btrim(search_term)) = %s
              and report_date > %s - (%s * interval '1 day')
              and report_date <= %s
              and is_settled
            group by 1, 2, 3, 4""",
        (tenant_id, term, through, lookback_days, through),
    )
    return cur.fetchall()


def _existing_target(cur, tenant_id: str, term: str, match_type: str):
    # marts has no RLS: the explicit tenant predicate is the isolation boundary.
    cur.execute(
        """select keyword_id, match_type, keyword_text
             from marts.mart_ppc_keyword_daily
            where tenant_id = %s
              and ((%s = 'exact' and lower(match_type) = 'exact'
                    and regexp_replace(lower(btrim(keyword_text)), '\\s+', ' ', 'g') = %s)
                or (%s = 'product'
                    and lower(coalesce(match_type, '')) not in ('exact', 'phrase', 'broad')
                    and regexp_replace(lower(btrim(keyword_text)),
                                       '^asin(-expanded)?=|"', '', 'g') = %s))
            order by keyword_id
            limit 1""",
        (tenant_id, match_type, term, match_type, term),
    )
    return cur.fetchone()


def _open_promotion(cur, tenant_id: str, term: str, match_type: str):
    cur.execute(
        """select l.id, l.action_id, a.status, l.destination_ad_group_id
             from search_term_harvest_lineage l
             join action a on a.id = l.action_id and a.tenant_id = l.tenant_id
            where l.tenant_id = %s and l.normalized_term = %s
              and l.destination_match_type = %s and a.status = any(%s)
            order by l.created_at, l.id
            limit 1""",
        (tenant_id, term, match_type, list(OPEN_ACTION_STATUSES)),
    )
    return cur.fetchone()


def _enabled_strategy_codes(cur, tenant_id: str) -> list[str]:
    cur.execute(
        """select code from (
               select distinct on (code) code, enabled
                 from strategy_version where tenant_id = %s
                order by code, version desc) latest
            where enabled""",
        (tenant_id,),
    )
    return [r["code"] for r in cur.fetchall()]


def _routes(cur, tenant_id: str) -> list[Route]:
    cur.execute(
        """select id, code, priority, asin, brand_class, match_type, strategy_code,
                  funnel_purpose, destination_campaign_id, destination_ad_group_id
             from search_term_harvest_route
            where tenant_id = %s and enabled""",
        (tenant_id,),
    )
    return [Route(**{**r, "id": str(r["id"])}) for r in cur.fetchall()]


def plan_harvest(
    cur,
    *,
    tenant_id: str,
    search_term: str,
    lookback_days: int,
    through: dt.date,
) -> HarvestPlan:
    """Resolve source, duplicates and destination for one harvest candidate."""
    term = normalize_term(search_term)
    source = choose_source(_fetch_sources(cur, tenant_id, term, lookback_days, through))
    if source is None:
        return HarvestPlan(ROUTE_MISSING, "no settled source rows for this search term")

    cur.execute(
        "select term, brand_class from search_term_brand_term where tenant_id = %s",
        (tenant_id,),
    )
    brand_terms = [(r["term"], r["brand_class"]) for r in cur.fetchall()]
    candidate = build_candidate(
        search_term,
        asin=source.advertised_asin,
        brand_terms=brand_terms,
        strategy_codes=_enabled_strategy_codes(cur, tenant_id),
    )

    existing = _existing_target(cur, tenant_id, term, candidate.match_type)
    if existing is not None:
        return HarvestPlan(
            DUPLICATE_TARGET,
            f"{candidate.match_type} target {existing['keyword_id']} already covers '{term}'",
            candidate,
            source,
        )
    promotion = _open_promotion(cur, tenant_id, term, candidate.match_type)
    if promotion is not None:
        return HarvestPlan(
            DUPLICATE_TARGET,
            f"'{term}' already promoted by action {promotion['action_id']} "
            f"({promotion['status']}) to ad group {promotion['destination_ad_group_id']}",
            candidate,
            source,
        )

    decision = select_route(candidate, _routes(cur, tenant_id))
    return HarvestPlan(decision.blocked_by, decision.reason, candidate, source, decision.route)


def record_lineage(
    cur,
    *,
    tenant_id: str,
    run_id: str,
    evaluation_id: str,
    action_id: str,
    plan: HarvestPlan,
) -> None:
    """Persist the immutable source -> destination record for a queued promotion."""
    if plan.blocked_by or plan.route is None or plan.candidate is None or plan.source is None:
        raise ValueError("only an allowed, routed harvest plan can record lineage")
    c, s, r = plan.candidate, plan.source, plan.route
    cur.execute(
        """insert into search_term_harvest_lineage (
               tenant_id, run_id, evaluation_id, action_id, route_id, route_code,
               search_term, normalized_term, asin, brand_class, funnel_purpose,
               strategy_code, source_campaign_id, source_ad_group_id, source_keyword_id,
               source_match_type, destination_campaign_id, destination_ad_group_id,
               destination_match_type, routing_reason, evidence)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            tenant_id, run_id, evaluation_id, action_id, r.id, r.code,
            c.search_term, c.normalized_term, c.asin, c.brand_class, c.funnel_purpose,
            r.strategy_code, s.campaign_id, s.ad_group_id, s.keyword_id, s.match_type,
            r.destination_campaign_id, r.destination_ad_group_id, c.match_type,
            plan.note, json.dumps(plan.evidence(), default=str),
        ),
    )
