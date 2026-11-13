from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/MARKETING_STREAM.md").read_text()
READINESS = (ROOT / "packages/db/migrations/0021_readiness_state.sql").read_text()


def test_marketing_stream_design_uses_existing_waiting_state_without_fake_rows():
    assert "WAITING_FOR_MARKETING_STREAM" in READINESS
    assert "dependency_key = 'amazon_marketing_stream'" in DOC
    assert "do not insert placeholder hourly rows" in DOC
    assert "LIVE_READY" in DOC


def test_marketing_stream_v2_delivery_is_versioned_and_idempotent():
    assert "S3 bucket" in DOC and "SQS queue" in DOC
    assert "Parquet" in DOC
    assert "highest batch" in DOC
    assert "all documented dimension fields" in DOC
    assert "not an additive delta" in DOC
