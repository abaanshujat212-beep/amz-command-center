import datetime as dt
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from services.ingest.pipelines import sales_traffic
from services.ingest.pipelines import sales_traffic_sandbox as sandbox

DAY = dt.date(2026, 8, 22)


class Connection:
    def __init__(self):
        self.raw = {}
        self.calls = []

    @contextmanager
    def transaction(self, *, force_rollback):
        assert force_rollback
        previous = dict(self.raw)
        try:
            yield
        finally:
            self.raw = previous

    def execute(self, stmt, params):
        self.calls.append((stmt, params))
        if "insert into raw." in stmt:
            self.raw[params[:3]] = params[3]
        if "count(*)" in stmt:
            tenant, date, asins = params
            return SimpleNamespace(fetchone=lambda: {
                "observed": sum((tenant, date, asin) in self.raw for asin in asins)
            })


class Client:
    def __init__(self, rows):
        self.rows = rows

    def create_report(self, report_type, start, end, report_options):
        assert report_type == sandbox.SALES_AND_TRAFFIC and start == end == DAY
        assert report_options == {"dateGranularity": "DAY", "asinGranularity": "CHILD"}
        return "private-report-id"

    def wait_for_report(self, report_id, timeout_s):
        assert report_id == "private-report-id" and timeout_s == 120
        return "private-document-id"

    def download_report(self, document_id):
        assert document_id == "private-document-id"
        return json.dumps({"salesAndTrafficByAsin": self.rows}).encode()


def test_smoke_replays_actual_upsert_in_a_rollback_only_transaction():
    conn = Connection()
    conn.raw[("another-tenant", DAY, "A")] = "keep"
    result = sandbox.smoke(conn, "sandbox-tenant", DAY, Client([{"childAsin": "A"}, {"childAsin": "B"}]))
    assert result == sandbox.SandboxEvidence(DAY, 2)
    assert conn.raw == {("another-tenant", DAY, "A"): "keep"}
    assert sum("insert into raw." in sql for sql, _ in conn.calls) == 4
    assert not any("sync_watermark" in sql or "pipeline_run" in sql for sql, _ in conn.calls)


@pytest.mark.parametrize("rows", [
    [],
    [{"childAsin": "A"}, {"childAsin": "A"}],
    [{"childAsin": "A", "date": "2026-08-23"}],
])
def test_bad_evidence_does_not_mutate_raw(rows):
    conn = Connection()
    with pytest.raises(sandbox.SandboxSmokeError):
        sandbox.smoke(conn, "tenant", DAY, Client(rows))
    assert not any("insert into raw." in sql for sql, _ in conn.calls)


def test_remote_error_does_not_expose_provider_detail():
    client = Client([])
    def fail(_document_id):
        raise ValueError("password=example&signed-download-url")
    client.download_report = fail
    with pytest.raises(sandbox.SandboxSmokeError, match=r"^download report: ValueError$"):
        sandbox.smoke(Connection(), "tenant", DAY, client)


@pytest.mark.parametrize("dsn", [
    "postgresql://myuser:mypass@localhost:5433/live",
    "postgresql://myuser:mypass@db.example.invalid/test",
    "hostaddr=8.8.8.8 host=localhost dbname=test",
])
def test_requires_disposable_loopback_database(monkeypatch, dsn):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@127.0.0.1:5432/live")
    monkeypatch.setenv("SPAPI_SANDBOX_DATABASE_URL", dsn)
    with pytest.raises(sandbox.SandboxSmokeError):
        sandbox._sandbox_dsn()


def test_accepts_explicit_isolated_local_db(monkeypatch):
    dsn = "postgresql://myuser:mypass@localhost:5433/sandbox"
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@127.0.0.1:5432/live")
    monkeypatch.setenv("SPAPI_SANDBOX_DATABASE_URL", dsn)
    assert sandbox._sandbox_dsn() == dsn


def test_sandbox_rejects_endpoint_override_and_does_not_fall_back_to_live_keys(monkeypatch):
    monkeypatch.setenv("SPAPI_ENDPOINT", "https://sellingpartnerapi-eu.amazon.com")
    with pytest.raises(sandbox.SandboxSmokeError, match="conflicts"):
        sandbox._sandbox_client()
    monkeypatch.delenv("SPAPI_ENDPOINT")
    monkeypatch.setenv("SPAPI_REFRESH_TOKEN", "ordinary-provider-key")
    monkeypatch.delenv("SPAPI_SANDBOX_REFRESH_TOKEN", raising=False)
    with pytest.raises(sandbox.SandboxSmokeError, match="dedicated"):
        sandbox._sandbox_client()


def test_dry_run_only_reads_watermark_and_never_reports_success(monkeypatch):
    class ReadOnly:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            assert sql.startswith("select last_complete_date")
            return SimpleNamespace(fetchone=lambda: {"last_complete_date": DAY - dt.timedelta(days=1)})

    monkeypatch.setattr(sales_traffic.psycopg, "connect", lambda *args, **kwargs: ReadOnly())
    def unexpected(_credentials):
        pytest.fail("A dry run opened the SP-API client")
    result = sales_traffic.run("tenant", dry_run=True, today=DAY + dt.timedelta(days=1), client_factory=unexpected)
    assert result.requested > 0
    assert result.succeeded == result.failed == result.rows_loaded == 0
