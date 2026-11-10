from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = (ROOT / "packages/db/migrations/0066_negative_product_target_action.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0066_negative_product_target_action.sql").read_text()


def test_negative_product_action_migration_adds_and_safely_removes_type():
    assert "add_negative_product" in UP
    assert "add_negative_product" in DOWN
    assert "cannot remove add_negative_product while action rows exist" in DOWN
