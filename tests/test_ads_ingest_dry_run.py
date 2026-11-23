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


@pytest.mark.parametrize(("rowcount", "expected"), [(1, "persisted"), (0, "connection_changed")])
def test_ads_rotated_token_is_encrypted_and_guarded(monkeypatch, rowcount, expected):
    monkeypatch.setenv("KEK_BASE64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    connection = ads_daily.AdsConnection(
        "eu", "client-id", "secret", "old-token", 123, "connection", b"existing-cipher", 1,
    )
    client = SimpleNamespace(credentials=SimpleNamespace(refresh_token="next-token"))

    def execute(sql, args):
        assert "tenant_id = %s and id = %s" in sql
        assert "refresh_token_encrypted = %s and key_version = %s" in sql
        assert ads_daily.unseal(args[0], args[1]) == "next-token"
        assert args[2:] == ("tenant", "connection", b"existing-cipher", 1)
        assert "old-token" not in repr(connection) and "secret" not in repr(connection)
        return SimpleNamespace(rowcount=rowcount)

    assert ads_daily.persist_rotated_refresh_token(SimpleNamespace(execute=execute), "tenant", connection, client) == expected

    client.credentials.refresh_token = "old-token"
    assert ads_daily.persist_rotated_refresh_token(None, "tenant", connection, client) == "unchanged"
