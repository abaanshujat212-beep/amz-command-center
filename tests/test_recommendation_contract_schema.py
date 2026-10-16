from pathlib import Path

ROOT=Path(__file__).parents[1]
UP=(ROOT/"packages/db/migrations/0061_recommendation_contract.sql").read_text(encoding="utf-8")
DOWN=(ROOT/"packages/db/migrations/down/0061_recommendation_contract.sql").read_text(encoding="utf-8")
ENGINE=(ROOT/"services/rules/engine.py").read_text(encoding="utf-8")
WEB=(ROOT/"apps/web/lib/recommendations.ts").read_text(encoding="utf-8")
LIST=(ROOT/"apps/web/app/api/ppc/recommendations/route.ts").read_text(encoding="utf-8")
DETAIL=(ROOT/"apps/web/app/api/ppc/recommendations/[id]/route.ts").read_text(encoding="utf-8")


def test_schema_extends_existing_queue_and_is_reversible():
    assert "alter table rule_evaluation" in UP and "alter table action" in UP
    assert "create table optimizer_run" in UP and "create table recommendation_evidence" in UP
    assert "force row level security" in UP
    assert "recommendation metadata is immutable" in UP
    assert "optimizer run is already finalized" in UP
    assert "unique(tenant_id,run_key)" in UP
    assert "unique(tenant_id,optimizer_run_id,evaluation_id,evidence_kind,source_ref)" in UP
    assert "drop table if exists recommendation_evidence" in DOWN
    assert "create table recommendation_queue" not in UP


def test_engine_emits_run_contract_and_source_attributed_evidence():
    for value in ("configuration_snapshots", "build_metadata", "insert into optimizer_run", "insert into recommendation_evidence", "update optimizer_run"):
        assert value in ENGINE
    assert "source_type" in UP and "source_ref" in UP and "completeness" in UP


def test_read_api_is_tenant_scoped_filterable_paginated_and_read_only():
    combined=WEB+LIST+DETAIL
    assert "withTenant(actor.tenantId" in combined
    assert "a.tenant_id=$1" in WEB
    for field in ("recommendation_type", "status", "confidence", "risk", "entity_type", "entity_id", "requested_at"):
        assert field in WEB
    assert "limit" in WEB and "offset" in WEB
    assert "actionCapability" in WEB and "dependencyState" in WEB
    assert "[redacted]" in WEB
    assert "export async function POST" not in combined
    assert "insert into action" not in combined
