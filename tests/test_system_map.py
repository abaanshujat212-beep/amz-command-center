"""The system map must not be able to rot quietly. See ADR 006 and #33.

A stale map produces confident wrong answers, which is strictly worse than no
copilot at all. Two bugs already shipped in this repo for exactly that reason: a
rule whose scope was never wired (skipped silently on every run), and a
documented dbt DAG that did not compile.

No database required — the static map is built from code and files, so these run
in CI before anything is provisioned.
"""

import pytest

from packages.shared import endpoints as ep
from services.copilot import system_map as sm
from services.ingest.pipelines.ads_daily import DATASETS
from services.rules.guardrails import Guard
from services.rules.query import SCOPE_SOURCES
from services.rules.rule_catalog import ALL_RULES

# The nine action types the database allows, per 0006. Written out rather than
# imported so that changing the constraint forces a conscious edit here.
EXPECTED_ACTION_TYPES = sorted(
    [
        "set_bid",
        "set_budget",
        "pause",
        "enable",
        "add_negative_exact",
        "add_negative_phrase",
        "create_keyword",
        "set_placement_modifier",
        "flag",
    ]
)

# Every scope the rule.scope CHECK permits.
ALL_SCOPES = [
    "campaign",
    "ad_group",
    "keyword",
    "target",
    "search_term",
    "placement",
    "asin",
]


# --- the map is buildable and complete ------------------------------------


def test_static_map_needs_no_database():
    """Debugging happens when things are down. A map that needs a live database
    is unavailable exactly when it is most needed."""
    m = sm.static_map()
    assert m["source"] == "code+files"
    assert m["rule_count"] == len(ALL_RULES)


def test_every_rule_appears_in_the_map_by_code():
    """Compare codes, not counts. In #28, 8 == 8 concealed three missing rules
    and three unplanned ones."""
    mapped = {r["code"] for r in sm.static_map()["rules"]}
    assert mapped == {r["code"] for r in ALL_RULES}


def test_every_rule_scope_is_wired():
    """The #27 bug: an unwired scope makes the engine skip the rule and still
    report the run as successful."""
    unwired = [r["code"] for r in ALL_RULES if r["scope"] not in SCOPE_SOURCES]
    assert unwired == [], f"rules with no mart behind them: {unwired}"


def test_every_rule_action_type_is_allowed_by_the_constraint():
    """A rule emitting an unlisted action type fails at insert, after the work."""
    bad = [
        (r["code"], r["action"]["type"])
        for r in ALL_RULES
        if r["action"]["type"] not in EXPECTED_ACTION_TYPES
    ]
    assert bad == []


def test_migration_parse_matches_the_nine_action_types():
    """Guards the weakest link in the map: a regex over SQL."""
    assert sm.action_types_from_migrations() == EXPECTED_ACTION_TYPES


def test_map_lists_every_migration_with_its_down_file():
    migrations = sm.static_map()["migrations"]
    assert len(migrations) >= 6
    forward_only = [m["name"] for m in migrations if not m["has_down"]]
    assert forward_only == [], f"no rollback path for: {forward_only}"


# --- blast radius ---------------------------------------------------------


def test_every_action_type_maps_to_an_endpoint_or_is_local_only():
    """Otherwise an action is approvable but not appliable, which is discovered
    only after a human has already said yes."""
    for action_type in EXPECTED_ACTION_TYPES:
        assert action_type in ep.ACTION_ENDPOINTS, f"{action_type} has no endpoint mapping"


@pytest.mark.parametrize("scope", ALL_SCOPES)
def test_a_flag_can_never_reach_an_endpoint(scope):
    """ADR 004's promise, pinned in code: diagnostics never leave the database."""
    assert ep.endpoint_for_action("flag", scope) is None


def test_mutating_endpoints_are_exactly_these_six():
    """The complete blast radius of this system. Adding a seventh way to change a
    client's account should require deleting a line from a test."""
    assert {e.key for e in ep.mutating()} == {
        "ads.campaigns.update",
        "ads.adGroups.update",
        "ads.keywords.update",
        "ads.keywords.create",
        "ads.targets.update",
        "ads.negativeKeywords.create",
    }


def test_unknown_action_type_raises_instead_of_returning_none():
    """None means 'never leaves the database'. A typo must not borrow that."""
    with pytest.raises(ep.UnknownEndpoint):
        ep.endpoint_for_action("set_bid_typo", "keyword")


def test_reading_endpoints_are_not_marked_mutating():
    """Creating a report is a POST that changes nothing. Mislabelling it would
    put report generation behind the approval gate for no reason."""
    assert ep.endpoint("ads.reports.create").mutates is False
    assert ep.endpoint("sp.reports.create").mutates is False


# --- secrets --------------------------------------------------------------


def test_config_keys_carry_no_values():
    """The .env holds the client's Amazon refresh tokens and the KEK. Only key
    NAMES may ever enter the map, because anything in the map reaches a model
    context and then a log line."""
    keys = sm.env_keys()
    assert "KEK_BASE64" in keys
    assert "TEST_DATABASE_URL" in keys
    for key in keys:
        assert "=" not in key
        assert "://" not in key
        assert key == key.strip()


def test_rendered_prompt_context_leaks_no_values():
    text = sm.render_for_prompt()
    assert "KEK_BASE64" in text
    assert "KEK_BASE64=" not in text
    for secret_ish in ("Atzr|", "Atza|"):
        assert secret_ish not in text


# --- Amazon's hard walls --------------------------------------------------


def test_lookback_windows_match_reality():
    """A wrong number here silently shortens the backfill, and those days are
    then unrecoverable from Amazon forever."""
    assert ep.ADS_REPORT_LOOKBACK_DAYS["spCampaigns"] == 95
    assert ep.ADS_REPORT_LOOKBACK_DAYS["sdCampaigns"] == 60


def test_every_ads_dataset_the_pipeline_requests_has_a_known_window():
    missing = sorted(
        {
            spec.kind
            for spec in DATASETS.values()
            if spec.kind not in ep.ADS_REPORT_LOOKBACK_DAYS
        }
    )
    assert missing == [], f"pipeline requests report kinds with no known lookback: {missing}"


def test_url_for_refuses_to_build_a_path_with_a_placeholder_left_in():
    """Otherwise the literal '{reportId}' is sent and Amazon returns a 404 that
    looks like a missing report rather than a bug."""
    with pytest.raises(ValueError):
        ep.url_for("sp.reports.get")
    assert ep.url_for("sp.reports.get", reportId="abc123").endswith(
        "/reports/2021-06-30/reports/abc123"
    )
    assert ep.url_for("ads.profiles.list").startswith("https://advertising-api-eu")


# --- guardrails and the self-check ----------------------------------------


def test_every_guardrail_can_be_explained_to_a_client():
    """An unexplained block is indistinguishable from a bug to the person whose
    campaign did not change."""
    unexplained = [g.name for g in Guard if g.name not in sm.GUARD_EXPLANATIONS]
    assert unexplained == []


def test_self_check_reports_no_errors():
    """Warnings and info are allowed; contradictions are not."""
    errors = [str(f) for f in sm.self_check() if f.severity == "error"]
    assert errors == []
