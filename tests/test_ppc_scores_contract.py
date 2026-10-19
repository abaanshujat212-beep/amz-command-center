from pathlib import Path

ROOT=Path(__file__).parents[1]
UP=(ROOT/"packages/db/migrations/0064_ppc_health_opportunity_scores.sql").read_text()
API=(ROOT/"apps/web/app/api/ppc/scores/route.ts").read_text()
PAGE=(ROOT/"apps/web/app/scores/page.tsx").read_text()

def test_scores_are_tenant_scoped_immutable_and_explainable():
    assert "force row level security" in UP.lower()
    assert "ppc_score_formula_immutable" in UP
    assert "ppc_score_snapshot_immutable" in UP
    assert "components jsonb" in UP and "coverage numeric" in UP
    assert "before update on ppc_score" in UP.lower()
    assert "before update or delete" not in UP.lower()

def test_formula_api_is_role_guarded_and_audited():
    library=(ROOT/"apps/web/lib/ppc-scores.ts").read_text()
    assert 'role!=="owner"&&role!=="admin"' in library
    assert "ppc_score.formula_created" in library
    assert "withTenant" in API

def test_ui_never_hides_missing_coverage():
    assert "Missing evidence lowers coverage" in PAGE
    assert 'c.available?c.value:"missing"' in PAGE
    dashboard=(ROOT/"apps/web/app/page.tsx").read_text()
    assert "latestScores" in dashboard and "coverage" in dashboard
