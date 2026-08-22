"""Diagnostic rules: findings, not changes.

The plan called for eight rules. The code shipped eight rules. The counts
matched, which is exactly why nobody noticed that three of the planned ones
were missing and three unplanned ones had taken their place (issue #28).

The three restored here all answer questions no bid change can answer:

  * plenty of impressions, nobody clicks   -> the LISTING is the problem
    (main image, title, price shown in search, review count)
  * plenty of clicks, nobody buys          -> the DETAIL PAGE is the problem
    (price, reviews, A+ content, out of stock, bad variation)
  * spending above break-even              -> tell me, do not touch it

The first was named in the plan as the differentiator: every cheap PPC tool
adjusts bids, and none of them tell you that no bid will fix a bad main image.
Raising a bid on a keyword with 20k impressions and 0.1% CTR just buys more
proof that the listing does not convert browsers into clickers.

The fourth, flag_low_cvr_placement, moved here from starter_rules (#27). It was
always named 'flag' and described "recommend only", but carried a real
set_placement_modifier mutation -- and a percentage modifier can only be
computed from the modifier already in place, which nothing ingests yet (#32).

Why these are 'flag' and not automated changes: the fix lives outside the ads
account. Nothing in the Ads API can rewrite a title or reshoot a photo, so a
rule that "acts" here could only act on the wrong lever -- lowering bids and
hiding the symptom while the real problem stays.

Thresholds are relative to the account's own CTR/CVR, never absolute. A 0.3%
CTR is normal for a broad discovery term and alarming for a branded exact, so
an absolute number would produce noise in one account and silence in another.
"""

from __future__ import annotations

DIAGNOSTIC_RULES: list[dict] = [
    {
        "code": "flag_low_ctr_listing",
        "name": "Impressions without clicks: listing/image problem",
        "description": (
            "Keyword gets plenty of impressions but under half the account CTR. "
            "No bid change fixes this; the main image, title, price or review "
            "count is losing the click."
        ),
        "scope": "keyword",
        "priority": 90,
        "lookback_days": 30,
        # A low-CTR finding is BY DEFINITION short of clicks, so the click
        # threshold must be 0. Impressions carry the statistical weight here:
        # the thin-data guardrail blocks only when clicks AND impressions are
        # both under their minimums.
        "min_clicks": 0,
        "min_impressions": 5000,
        "condition": {
            "and": [
                {">=": [{"var": "impressions"}, 5000]},
                {"<": [{"var": "ctr"}, {"*": [{"var": "account_ctr"}, 0.5]}]},
            ]
        },
        "action": {"type": "flag", "severity": "warning", "diagnosis": "listing_or_image"},
        "reason_template": (
            "{impressions} impressions but CTR {ctr:.2%} is under half the account "
            "average {account_ctr:.2%}. Shoppers see this listing and scroll past: "
            "check main image, title, price and review count. A bid change cannot "
            "fix a click problem."
        ),
    },
    {
        "code": "flag_low_cvr_detail_page",
        "name": "Clicks without orders: price/review problem",
        "description": (
            "Keyword earns clicks at or above account CTR but converts at under "
            "half the account CVR. The ad works; the detail page does not."
        ),
        "scope": "keyword",
        "priority": 91,
        "lookback_days": 30,
        "min_clicks": 30,
        "min_impressions": 500,
        "condition": {
            "and": [
                {">=": [{"var": "clicks"}, 30]},
                {">=": [{"var": "ctr"}, {"var": "account_ctr"}]},
                {"<": [{"var": "cvr"}, {"*": [{"var": "account_cvr"}, 0.5]}]},
            ]
        },
        "action": {"type": "flag", "severity": "warning", "diagnosis": "price_or_reviews"},
        "reason_template": (
            "CTR {ctr:.2%} is healthy but CVR {cvr:.2%} is under half the account "
            "average {account_cvr:.2%} over {clicks} clicks and {cost:.2f} spend. "
            "Shoppers arrive and leave: check price vs competitors, review count "
            "and rating, stock status, and whether the variation shown matches "
            "what the keyword promises."
        ),
    },
    {
        "code": "flag_above_break_even",
        "name": "Campaign spending above break-even (report only)",
        "description": (
            "Campaign ACOS is above its break-even ACOS. Reported, never changed "
            "automatically: the right response may be a price rise, a cost fix or "
            "a deliberate launch loss, none of which a bid rule can decide."
        ),
        "scope": "campaign",
        "priority": 92,
        "lookback_days": 14,
        "min_clicks": 100,
        "min_impressions": 2000,
        "condition": {
            "and": [
                {">": [{"var": "acos"}, {"var": "break_even_acos"}]},
                {">=": [{"var": "attributed_orders"}, 5]},
            ]
        },
        "action": {"type": "flag", "severity": "critical", "diagnosis": "unprofitable_spend"},
        "reason_template": (
            "ACOS {acos:.1%} is above break-even {break_even_acos:.1%} over "
            "{lookback_days} days: {cost:.2f} spent for {attributed_sales:.2f} sales "
            "across {attributed_orders} orders. Every order is losing contribution. "
            "Decide deliberately: raise price, cut cost, cut spend, or accept it as "
            "launch investment."
        ),
    },
    {
        "code": "flag_low_cvr_placement",
        "name": "Placement converting far below the account (report only)",
        "description": (
            "One placement -- top of search, product page or rest of search -- "
            "converts at under half the account CVR. The lever is a placement bid "
            "modifier on the campaign, which is applied by hand for now: the "
            "current modifier is not ingested, and a percentage change computed "
            "from an assumed 0% would silently overwrite one the seller set."
        ),
        "scope": "placement",
        "priority": 93,
        "lookback_days": 30,
        "min_clicks": 100,
        "min_impressions": 5000,
        "condition": {
            "and": [
                {">=": [{"var": "clicks"}, 100]},
                {"<": [{"var": "cvr"}, {"*": [{"var": "account_cvr"}, 0.5]}]},
            ]
        },
        "action": {"type": "flag", "severity": "warning", "diagnosis": "placement_mix"},
        "reason_template": (
            "This placement converts at {cvr:.2%} against an account average of "
            "{account_cvr:.2%} over {clicks} clicks and {cost:.2f} spend. Consider a "
            "negative placement modifier on the campaign, or check whether the "
            "traffic this slot sends matches the product at all."
        ),
    },
]
