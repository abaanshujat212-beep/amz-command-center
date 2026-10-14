import datetime as dt

import pytest

from services.notifications.delivery import (
    AdapterResult,
    ApprovedTemplate,
    accept_verified_callback,
    record_attempt,
    render_template,
    retry_at,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 14, 10, tzinfo=UTC)


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((" ".join(sql.split()), params))
        return Cursor(next(self.rows, None))


def template(**overrides):
    values = dict(
        template_id="t1",
        channel="email",
        subject="${title}",
        body="${title}: ${summary}",
        variable_allowlist=frozenset({"title", "summary"}),
    )
    values.update(overrides)
    return ApprovedTemplate(**values)


def test_templates_only_render_allowlisted_scalar_data():
    rendered = render_template(template(), {"title": "Stock", "summary": 4, "secret": "omit"})
    assert rendered.subject == "Stock"
    assert rendered.body == "Stock: 4"
    with pytest.raises(ValueError, match="allowlist"):
        render_template(template(body="${token}"), {"token": "secret"})
    with pytest.raises(ValueError, match="scalar"):
        render_template(template(), {"title": "Stock", "summary": {"raw": "payload"}})


def test_retry_schedule_is_deterministic_and_capped():
    assert retry_at(1, NOW) == NOW + dt.timedelta(minutes=1)
    assert retry_at(3, NOW) == NOW + dt.timedelta(minutes=25)
    assert retry_at(8, NOW) == NOW + dt.timedelta(hours=6)


def test_retry_exhaustion_moves_to_dead_letter_with_append_only_attempt():
    conn = Connection([{"id": "attempt"}, None])
    status = record_attempt(
        conn,
        tenant_id="tenant",
        delivery_id="delivery",
        attempt_number=5,
        max_attempts=5,
        idempotency_key="delivery:5",
        result=AdapterResult("RETRYABLE", error_code="429"),
        attempted_at=NOW,
    )
    assert status == "DEAD_LETTER"
    assert "insert into notification_delivery_attempt" in conn.calls[0][0]
    assert conn.calls[1][1][0] == "DEAD_LETTER"
    assert conn.calls[1][1][4] == NOW


def test_attempt_idempotency_does_not_double_count_cost():
    conn = Connection([None, {"outcome": "DELIVERED"}])
    status = record_attempt(
        conn,
        tenant_id="tenant",
        delivery_id="delivery",
        attempt_number=1,
        max_attempts=5,
        idempotency_key="delivery:1",
        result=AdapterResult("DELIVERED", cost_amount=0.01, cost_currency="GBP"),
        attempted_at=NOW,
    )
    assert status == "DELIVERED"
    assert len(conn.calls) == 2


def test_callback_requires_adapter_verified_signature_and_is_idempotent():
    with pytest.raises(ValueError, match="signature"):
        accept_verified_callback(
            Connection([]),
            tenant_id="tenant",
            delivery_id="delivery",
            channel="email",
            callback_id="cb",
            status="DELIVERED",
            provider_reference="p",
            signature_verified=False,
        )
    duplicate = Connection([None])
    assert (
        accept_verified_callback(
            duplicate,
            tenant_id="tenant",
            delivery_id="delivery",
            channel="email",
            callback_id="cb",
            status="DELIVERED",
            provider_reference="p",
            signature_verified=True,
        )
        is False
    )
    assert len(duplicate.calls) == 1
