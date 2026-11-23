from datetime import date
from types import SimpleNamespace

import pytest

from services.ingest.pipelines import ads_daily


def test_ads_dry_run_only_reads_watermarks_and_counts_planned_requests(monkeypatch):
    dataset = "ads_sp_campaign_daily"

    class ReadOnly:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            assert sql.startswith("select last_complete_date")
            assert params == ("tenant", dataset)
            return SimpleNamespace(fetchone=lambda: {"last_complete_date": date(2026, 8, 20)})

    monkeypatch.setattr(ads_daily.psycopg, "connect", lambda *a, **kw: ReadOnly())

    def unexpected_client(_connection):
        pytest.fail("The dry run must never instantiate an API client")

    result = ads_daily.run(
        "tenant", dry_run=True, today=date(2026, 8, 23),
        datasets=[dataset], client_factory=unexpected_client,
    )
    assert result.dry_run and result.succeeded == result.failed == 0
    assert len(result.datasets) == 1
    assert result.datasets[0].requested > 0
    assert result.datasets[0].dataset == dataset
    assert result.datasets[0].rows_loaded == 0
