from services.rules.harvest import (
    DUPLICATE_TARGET,
    ROUTE_CONFLICT,
    ROUTE_MISSING,
    HarvestPlan,
    Route,
    build_candidate,
    choose_source,
    classify_brand,
    destination_match_type,
    normalize_term,
    select_route,
)

BRANDS = [("axaty", "own_brand"), ("velcro", "competitor"), ("axaty pro", "competitor")]


def _route(code, **kw):
    base = {
        "id": f"id-{code}",
        "code": code,
        "priority": 100,
        "asin": "*",
        "brand_class": "*",
        "match_type": "exact",
        "strategy_code": "*",
        "funnel_purpose": "performance",
        "destination_campaign_id": "C-PERF",
        "destination_ad_group_id": "G-PERF",
    }
    base.update(kw)
    return Route(**base)


def _candidate(term="hook and loop tape", asin="B000TEST01", strategies=("harvest",)):
    return build_candidate(term, asin=asin, brand_terms=BRANDS, strategy_codes=strategies)


def test_normalization_and_match_type():
    assert normalize_term("  Hook   AND loop ") == "hook and loop"
    assert destination_match_type("B07XYZ1234") == "product"
    assert destination_match_type("b07xyz1234 tape") == "exact"


def test_brand_classification_uses_whole_words_and_longest_term():
    assert classify_brand("axaty tape", BRANDS) == ("own_brand", "axaty")
    assert classify_brand("axaty pro tape", BRANDS) == ("competitor", "axaty pro")
    assert classify_brand("velcrostrip", BRANDS) == ("generic", None)
    c = _candidate("velcro straps")
    assert (c.brand_class, c.funnel_purpose) == ("competitor", "conquest")


def test_source_selection_is_deterministic():
    rows = [
        {"campaign_id": "C2", "ad_group_id": "G2", "orders": 3, "sales": 30, "clicks": 9},
        {"campaign_id": "C1", "ad_group_id": "G9", "orders": 5, "sales": 40, "clicks": 20},
        {"campaign_id": "C1", "ad_group_id": "G1", "orders": 5, "sales": 40, "clicks": 20},
    ]
    assert choose_source(rows).ad_group_id == "G1"
    assert choose_source(list(reversed(rows))).ad_group_id == "G1"
    assert choose_source([]) is None


def test_most_specific_route_wins_then_priority():
    routes = [
        _route("generic_exact", priority=1),
        _route("asin_exact", asin="B000TEST01", destination_ad_group_id="G-ASIN", priority=50),
        _route(
            "asin_harvest",
            asin="B000TEST01",
            strategy_code="harvest",
            destination_ad_group_id="G-HARVEST",
            priority=90,
        ),
    ]
    decision = select_route(_candidate(), routes)
    assert decision.route.code == "asin_harvest"
    assert decision.blocked_by is None
    assert "specificity 2" in decision.reason and "G-HARVEST" in decision.reason
    assert decision.considered == ("asin_harvest", "asin_exact", "generic_exact")


def test_strategy_asin_match_type_and_funnel_filter_routes():
    routes = [
        _route("launch_only", strategy_code="launch"),
        _route("other_asin", asin="B000OTHER1"),
        _route("product_only", match_type="product"),
        _route("defense_only", funnel_purpose="brand_defense"),
    ]
    decision = select_route(_candidate(), routes)
    assert decision.route is None and decision.blocked_by == ROUTE_MISSING
    unknown_asin = select_route(_candidate(asin=None), [_route("asin", asin="B000TEST01")])
    assert unknown_asin.blocked_by == ROUTE_MISSING


def test_product_and_brand_routes():
    product = select_route(
        _candidate("B07XYZ1234"), [_route("pat", match_type="product"), _route("kw")]
    )
    assert product.route.code == "pat"
    own = select_route(
        _candidate("axaty tape"),
        [_route("defense", funnel_purpose="brand_defense", brand_class="own_brand"),
         _route("perf")],
    )
    assert own.route.code == "defense"


def test_competing_destinations_block_but_identical_destinations_do_not():
    conflict = select_route(
        _candidate(), [_route("a"), _route("b", destination_ad_group_id="G-OTHER")]
    )
    assert conflict.route is None and conflict.blocked_by == ROUTE_CONFLICT
    assert "a, b" in conflict.reason
    same = select_route(_candidate(), [_route("b"), _route("a")])
    assert same.route.code == "a"


def test_plan_evidence_is_json_ready_and_carries_destination():
    candidate = _candidate()
    route = _route("generic_exact")
    plan = HarvestPlan(None, "route generic_exact ...", candidate, None, route)
    evidence = plan.evidence()
    assert evidence["candidate"]["strategy_codes"] == ["harvest"]
    assert evidence["destination"] == {
        "campaign_id": "C-PERF",
        "ad_group_id": "G-PERF",
        "match_type": "exact",
        "route_code": "generic_exact",
    }
    blocked = HarvestPlan(DUPLICATE_TARGET, "exact target K1 already covers", candidate)
    assert blocked.destination is None
    assert blocked.evidence()["blocked_by"] == DUPLICATE_TARGET
