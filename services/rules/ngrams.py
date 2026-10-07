"""Deterministic negative n-gram analysis over settled search terms.

Waste often hides in phrases shared by many queries ("free", "for kids") rather
than in any single query. This module tokenizes every settled search term,
aggregates 1-3 word phrases across the queries that contain them, and emits
confidence-gated recommendations. Nothing is sent to Amazon: a
``negative_phrase`` finding is a recommendation for review, and anything that is
ambiguous, thin or protected stays ``manual_review`` or ``protected``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field

import psycopg
from psycopg.rows import dict_row

from services.rules.freshness import resolve_source_freshness
from services.rules.settings import load_tenant_guard_config

TOKEN = re.compile(r"[a-z0-9]+")
APOSTROPHES = re.compile(r"['\u2018\u2019`]")
STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or the to with without".split()
)
MAX_N = 3
MAX_EVIDENCE_QUERIES = 100

NEGATIVE_PHRASE = "negative_phrase"
MANUAL_REVIEW = "manual_review"
PROTECTED = "protected"
COVERED = "covered"


@dataclass(frozen=True)
class Thresholds:
    review_min_clicks: int = 10
    min_clicks: int = 20
    min_cost: float = 10.0
    min_queries: int = 2
    auto_min_n: int = 2
    max_chance_zero_orders: float = 0.05


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class Protection:
    protection_id: str
    value: str


@dataclass
class NgramFinding:
    ngram: str
    n: int
    query_count: int
    clicks: int
    impressions: int
    cost: float
    orders: int
    sales: float
    chance_zero_orders: float | None
    decision: str = MANUAL_REVIEW
    reasons: list[str] = field(default_factory=list)
    protection_id: str | None = None
    contributing_queries: list[dict] = field(default_factory=list)


def tokenize(term: str) -> tuple[str, ...]:
    """Lowercase, strip accents and apostrophes, split on anything else."""
    text = unicodedata.normalize("NFKD", str(term).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return tuple(TOKEN.findall(APOSTROPHES.sub("", text)))


def phrases(tokens: Sequence[str], max_n: int = MAX_N) -> set[str]:
    """Distinct contiguous 1..max_n word phrases; each counts once per query."""
    return {
        " ".join(tokens[i : i + n])
        for n in range(1, max_n + 1)
        for i in range(len(tokens) - n + 1)
    }


def _contains(outer: Sequence[str], inner: Sequence[str]) -> bool:
    k = len(inner)
    return k > 0 and any(tuple(outer[i : i + k]) == tuple(inner) for i in range(len(outer) - k + 1))


def _is_generic(tokens: Sequence[str]) -> bool:
    return all(t in STOPWORDS or t.isdigit() or len(t) < 3 for t in tokens)


def _protection_for(tokens: Sequence[str], protections: Iterable[Protection]) -> str | None:
    # Overlap in either direction is protected: a phrase inside a protected term
    # would block it, and a protected term inside the phrase means the phrase is
    # about something the seller explicitly wants to keep.
    for p in protections:
        protected = tokenize(p.value)
        if _contains(protected, tokens) or _contains(tokens, protected):
            return p.protection_id
    return None


def analyze(
    rows: Iterable[Mapping],
    protections: Iterable[Protection] = (),
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[NgramFinding]:
    """Aggregate phrases across queries and classify zero-order waste.

    ``rows`` are per-query aggregates with search_term, clicks, impressions,
    cost, orders and sales. Output order is deterministic: n, then ngram.
    """
    protections = list(protections)
    queries: dict[str, dict] = {}
    for row in rows:
        tokens = tokenize(row["search_term"])
        if not tokens:
            continue
        key = " ".join(tokens)
        q = queries.setdefault(
            key,
            {"search_term": key, "clicks": 0, "impressions": 0, "cost": 0.0,
             "orders": 0, "sales": 0.0, "campaign_ids": set(), "tokens": tokens},
        )
        q["clicks"] += int(row.get("clicks") or 0)
        q["impressions"] += int(row.get("impressions") or 0)
        q["cost"] += float(row.get("cost") or 0)
        q["orders"] += int(row.get("orders") or 0)
        q["sales"] += float(row.get("sales") or 0)
        q["campaign_ids"].update(c for c in row.get("campaign_ids") or () if c)

    total_clicks = sum(q["clicks"] for q in queries.values())
    total_orders = sum(q["orders"] for q in queries.values())
    account_cvr = total_orders / total_clicks if total_clicks and total_orders else None

    members: dict[str, list[dict]] = {}
    for q in queries.values():
        for phrase in phrases(q["tokens"]):
            members.setdefault(phrase, []).append(q)

    findings: list[NgramFinding] = []
    for phrase, qs in members.items():
        clicks = sum(q["clicks"] for q in qs)
        orders = sum(q["orders"] for q in qs)
        # Any converting query containing the phrase makes it a non-candidate:
        # negating it would also block that converter.
        if orders > 0 or clicks < thresholds.review_min_clicks:
            continue
        tokens = tuple(phrase.split())
        chance = math.exp(-clicks * account_cvr) if account_cvr else None
        ordered = sorted(qs, key=lambda q: (-q["clicks"], q["search_term"]))
        finding = NgramFinding(
            ngram=phrase,
            n=len(tokens),
            query_count=len(qs),
            clicks=clicks,
            impressions=sum(q["impressions"] for q in qs),
            cost=round(sum(q["cost"] for q in qs), 4),
            orders=0,
            sales=round(sum(q["sales"] for q in qs), 4),
            chance_zero_orders=round(chance, 6) if chance is not None else None,
            contributing_queries=[
                {"search_term": q["search_term"], "clicks": q["clicks"],
                 "impressions": q["impressions"], "cost": round(q["cost"], 4),
                 "orders": q["orders"], "campaign_ids": sorted(q["campaign_ids"])}
                for q in ordered[:MAX_EVIDENCE_QUERIES]
            ],
        )
        if clicks < thresholds.min_clicks or finding.cost < thresholds.min_cost:
            finding.reasons.append("low_volume")
        if len(qs) < thresholds.min_queries:
            finding.reasons.append("few_queries")
        if finding.n < thresholds.auto_min_n:
            finding.reasons.append("single_word")
        if _is_generic(tokens):
            finding.reasons.append("generic_tokens")
        if chance is None or chance > thresholds.max_chance_zero_orders:
            finding.reasons.append("low_confidence")
        finding.protection_id = _protection_for(tokens, protections)
        if finding.protection_id:
            finding.decision = PROTECTED
            finding.reasons.append("protected_term")
        elif not finding.reasons:
            finding.decision = NEGATIVE_PHRASE
        findings.append(finding)

    findings.sort(key=lambda f: (f.n, f.ngram))
    negated: list[tuple[str, ...]] = []
    for f in findings:
        if f.decision != NEGATIVE_PHRASE:
            continue
        tokens = tuple(f.ngram.split())
        cover = next((c for c in negated if _contains(tokens, c)), None)
        if cover:
            f.decision = COVERED
            f.reasons.append(f"covered_by:{' '.join(cover)}")
        else:
            negated.append(tokens)
    return findings


def fetch_queries(cur, *, tenant_id: str, lookback_days: int, through: dt.date) -> list[dict]:
    # Marts have no RLS: the tenant predicate is the isolation boundary.
    # Already-negated queries no longer spend, so they are not evidence.
    cur.execute(
        """
        select search_term,
               sum(clicks) clicks, sum(impressions) impressions, sum(cost) cost,
               sum(attributed_orders_7d) orders, sum(attributed_sales_7d) sales,
               array_agg(distinct campaign_id) campaign_ids
          from marts.mart_ppc_search_term_daily
         where tenant_id = %s
           and report_date >  %s - (%s * interval '1 day')
           and report_date <= %s
           and is_settled
         group by search_term
        having not bool_or(is_already_negative)
        """,
        (tenant_id, through, lookback_days, through),
    )
    return cur.fetchall()


def load_protections(cur, *, tenant_id: str, now: dt.datetime) -> list[Protection]:
    cur.execute(
        """
        select p.id, p.entity_value
          from entity_protection p
         where p.tenant_id = %s
           and p.entity_type in ('keyword','search_term')
           and p.policy in ('allow','protect')
           and (p.expires_at is null or p.expires_at > %s)
           and coalesce((select e.event_type from entity_protection_event e
                          where e.tenant_id = p.tenant_id and e.protection_id = p.id
                          order by e.occurred_at desc, e.id desc limit 1), 'created')
               not in ('released','consumed')
         order by p.created_at, p.id
        """,
        (tenant_id, now),
    )
    return [Protection(str(r["id"]), r["entity_value"]) for r in cur.fetchall()]


@dataclass
class NgramRun:
    run_id: str
    tenant_id: str
    status: str
    data_through: dt.date | None = None
    queries_analyzed: int = 0
    decisions: dict = field(default_factory=dict)
    detail: str | None = None


def run_analysis(
    conn: psycopg.Connection,
    tenant_id: str,
    *,
    lookback_days: int = 30,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    now: dt.datetime | None = None,
) -> NgramRun:
    now = now or dt.datetime.now(dt.timezone.utc)
    result = NgramRun(run_id=str(uuid.uuid4()), tenant_id=tenant_id, status="success")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cfg = load_tenant_guard_config(cur, tenant_id)
        freshness = resolve_source_freshness(
            cur,
            tenant_id=tenant_id,
            scope="search_term",
            now=now,
            settled_cutoff=now.date() - dt.timedelta(days=cfg.settlement_lag_days),
            max_age_hours=cfg.max_data_age_hours,
        )
        if not freshness.usable:
            result.status, result.detail = freshness.block_reason, freshness.detail
            return result
        result.data_through = freshness.data_through
        rows = fetch_queries(
            cur, tenant_id=tenant_id, lookback_days=lookback_days, through=freshness.data_through
        )
        result.queries_analyzed = len(rows)
        findings = analyze(rows, load_protections(cur, tenant_id=tenant_id, now=now), thresholds)
        for f in findings:
            result.decisions[f.decision] = result.decisions.get(f.decision, 0) + 1
            cur.execute(
                """
                insert into search_term_ngram_recommendation(
                  tenant_id, run_id, ngram, n, decision, reasons, query_count, clicks,
                  impressions, cost, orders, sales, chance_zero_orders, protection_id,
                  contributing_queries, thresholds, lookback_days, data_through)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id, result.run_id, f.ngram, f.n, f.decision, f.reasons,
                    f.query_count, f.clicks, f.impressions, f.cost, f.orders, f.sales,
                    f.chance_zero_orders, f.protection_id,
                    json.dumps(f.contributing_queries), json.dumps(asdict(thresholds)),
                    lookback_days, freshness.data_through,
                ),
            )
    conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Negative n-gram analysis for one tenant")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    url = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
    with psycopg.connect(url) as conn:
        print(asdict(run_analysis(conn, args.tenant_id, lookback_days=args.lookback_days)))


if __name__ == "__main__":
    main()
