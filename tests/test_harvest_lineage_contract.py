from pathlib import Path

from services.copilot.system_map import GUARD_EXPLANATIONS
from services.rules.guardrails import Guard
from services.rules.harvest import DUPLICATE_TARGET, ROUTE_CONFLICT, ROUTE_MISSING

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0047_search_term_harvest_lineage.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0047_search_term_harvest_lineage.sql").read_text()
ENGINE = (ROOT / "services/rules/engine.py").read_text()
MART = (ROOT / "packages/dbt/models/marts/mart_ppc_search_term_daily.sql").read_text()


def test_lineage_is_immutable_tenant_scoped_and_reversible():
    assert "search_term_harvest_lineage_immutable" in UP
    assert "force row level security" in UP
    assert "unique (tenant_id,action_id)" in UP
    for table in ("search_term_harvest_lineage", "search_term_harvest_route",
                  "search_term_brand_term"):
        assert f"drop table if exists {table}" in DOWN


def test_harvest_blocks_are_explained_guards():
    for value in (DUPLICATE_TARGET, ROUTE_MISSING, ROUTE_CONFLICT):
        assert Guard(value).name in GUARD_EXPLANATIONS


def test_engine_routes_harvest_and_records_lineage():
    assert "plan_harvest(" in ENGINE
    assert "record_lineage(" in ENGINE
    assert 'metrics["harvest_routing"]' in ENGINE
    assert "advertised_asin" in MART
