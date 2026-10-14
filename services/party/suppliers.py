"""Supplier CRM commands. Callers own transactions and set tenant/RBAC context."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class QuoteInput:
    product_id: str
    quote_ref: str
    quoted_on: date
    currency: str
    unit_price: Decimal
    valid_until: date | None = None
    moq: Decimal | None = None
    lead_days: int | None = None


def add_quote_version(conn, tenant_id: str, supplier_id: str, value: QuoteInput, actor_user_id: str | None = None) -> dict:
    currency = value.currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter ISO code")
    if value.unit_price < 0 or (value.valid_until and value.valid_until < value.quoted_on):
        raise ValueError("invalid quote price or validity")
    current = conn.execute(
        """select id,version from supplier_quote where tenant_id=%s and supplier_party_id=%s
           and quote_ref=%s and superseded_at is null for update""",
        (tenant_id, supplier_id, value.quote_ref.strip()),
    ).fetchone()
    version = int(current[1]) + 1 if current else 1
    if current:
        conn.execute("update supplier_quote set superseded_at=now() where tenant_id=%s and id=%s", (tenant_id, current[0]))
    row = conn.execute(
        """insert into supplier_quote(tenant_id,supplier_party_id,supplier_product_id,quote_ref,version,quoted_on,valid_until,currency,unit_price,moq,lead_days,created_by)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
        (tenant_id,supplier_id,value.product_id,value.quote_ref.strip(),version,value.quoted_on,value.valid_until,currency,value.unit_price,value.moq,value.lead_days,actor_user_id),
    ).fetchone()
    conn.execute("insert into supplier_timeline_event(tenant_id,supplier_party_id,event_type,summary,detail,actor_user_id) values(%s,%s,'quote.versioned',%s,%s::jsonb,%s)", (tenant_id,supplier_id,f"Quote {value.quote_ref} v{version}",f'{{"quote_id":"{row[0]}","version":{version}}}',actor_user_id))
    return dict(row)


def quote_freshness(valid_until: date | None, today: date, stale_after_days: int = 90) -> str:
    if valid_until is None:
        return "unknown"
    if valid_until < today:
        return "expired"
    return "stale_soon" if (valid_until - today).days <= stale_after_days else "current"
