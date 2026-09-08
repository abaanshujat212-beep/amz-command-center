import pytest

from packages.db.seed_spapi_sandbox_demo import PRODUCTS, _require_sandbox


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, row=(1,)):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return FakeResult(self.row)


def test_sandbox_demo_refuses_production_endpoint(monkeypatch):
    monkeypatch.setenv("SPAPI_ENDPOINT", "https://sellingpartnerapi-eu.amazon.com")
    conn = FakeConn()
    with pytest.raises(RuntimeError, match="not an Amazon sandbox host"):
        _require_sandbox(conn, "tenant-1")
    assert conn.calls == []


def test_sandbox_demo_requires_sandbox_selling_account(monkeypatch):
    monkeypatch.setenv(
        "SPAPI_ENDPOINT", "https://sandbox.sellingpartnerapi-eu.amazon.com"
    )
    with pytest.raises(RuntimeError, match="no sandbox selling account"):
        _require_sandbox(FakeConn(row=None), "tenant-1")


def test_sandbox_demo_fixture_is_clearly_namespaced(monkeypatch):
    monkeypatch.setenv(
        "SPAPI_ENDPOINT", "https://sandbox.sellingpartnerapi-eu.amazon.com"
    )
    _require_sandbox(FakeConn(), "tenant-1")
    assert PRODUCTS
    assert all(asin.startswith("B0SANDBOX") for asin, *_ in PRODUCTS)
    assert all(sku.startswith("SANDBOX-SKU-") for _, sku, *_ in PRODUCTS)
