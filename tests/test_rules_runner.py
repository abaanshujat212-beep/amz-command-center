from services.rules.engine import RunSummary
from services.rules.runner import summary_line


def test_summary_line_is_operator_readable():
    summary = RunSummary(
        run_id="run-1",
        tenant_id="tenant-1",
        rules_run=2,
        entities_evaluated=10,
        matched=3,
        proposed=1,
        flagged=2,
        errors=["bad rule"],
    )
    line = summary_line(summary)
    assert "tenant=tenant-1" in line
    assert "proposed=1" in line
    assert "flagged=2" in line
    assert "errors=1" in line
