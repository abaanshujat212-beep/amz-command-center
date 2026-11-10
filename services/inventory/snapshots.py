"""Tenant-scoped inventory location and idempotent snapshot persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

LOCATION_TYPES = {
    "amazon_fba", "amazon_awd", "own_warehouse", "third_party_logistics",
    "prep_center", "supplier", "in_transit", "other",
}
SOURCE_TYPES = {
    "amazon_api", "manual", "csv_import", "supplier_connector",
    "warehouse_connector", "approved_provider",
}
QUANTITY_FIELDS = (
    "on_hand_qty", "available_qty", "reserved_qty", "inbound_qty",
    "unsellable_qty", "committed_qty", "in_transit_qty",
)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _quantity(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a nonnegative quantity or unknown")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a nonnegative quantity or unknown") from exc
    if not number.is_finite() or number < 0 or number.as_tuple().exponent < -4:
        raise ValueError(f"{name} must be a nonnegative quantity with at most four decimals")
    return number


def save_location(
    conn,
    *,
    tenant_id: str,
    location_code: str,
    location_type: str,
    display_name: str,
    marketplace_id: str | None = None,
    external_location_id: str | None = None,
) -> str:
    """Create or refresh one tenant's named location and return its ID."""
    tenant = _required_text(tenant_id, "tenant_id")
    code = _required_text(location_code, "location_code")
    name = _required_text(display_name, "display_name")
    if location_type not in LOCATION_TYPES:
        raise ValueError("unsupported inventory location type")
    if location_type == "amazon_fba" and not marketplace_id:
        raise ValueError("Amazon FBA locations require a marketplace")
    with conn.cursor() as cur:
        cur.execute(
            """insert into inventory_location
                 (tenant_id,location_code,location_type,display_name,marketplace_id,external_location_id)
               values (%s,%s,%s,%s,%s,%s)
               on conflict (tenant_id,location_code) do update set
                 location_type=excluded.location_type,display_name=excluded.display_name,
                 marketplace_id=excluded.marketplace_id,external_location_id=excluded.external_location_id,
                 active=true
               returning id::text""",
            (tenant, code, location_type, name, marketplace_id, external_location_id),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("inventory location write returned no ID")
    return row["id"]


def save_snapshot(
    conn,
    *,
    tenant_id: str,
    location_id: str,
    sku: str,
    source_type: str,
    source_reference: str,
    observed_at: datetime,
    freshness_state: str = "current",
    source_provider_id: str | None = None,
    expected_available_at: datetime | None = None,
    currency: str | None = None,
    source_payload: Mapping[str, Any] | None = None,
    **quantities: Any,
) -> tuple[str, bool]:
    """Insert an append-only snapshot; duplicate source keys return existing ID.

    Quantity fields remain SQL NULL when absent, preserving unknown vs zero.
    The caller owns transaction boundaries and must establish the tenant RLS
    setting before invoking this method.
    """
    tenant = _required_text(tenant_id, "tenant_id")
    location = _required_text(location_id, "location_id")
    item = _required_text(sku, "sku")
    reference = _required_text(source_reference, "source_reference")
    if source_type not in SOURCE_TYPES:
        raise ValueError("unsupported inventory source type")
    if source_type == "approved_provider" and not source_provider_id:
        raise ValueError("approved provider snapshots require source_provider_id")
    if freshness_state not in {"current", "stale", "partial", "unknown"}:
        raise ValueError("unsupported inventory freshness state")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    if expected_available_at is not None and (
        not isinstance(expected_available_at, datetime) or expected_available_at.tzinfo is None
    ):
        raise ValueError("expected_available_at must include a timezone")
    if currency is not None and (len(currency) != 3 or not currency.isalpha() or currency.upper() != currency):
        raise ValueError("currency must be a three-letter uppercase code")
    unknown_fields = set(quantities) - set(QUANTITY_FIELDS)
    if unknown_fields:
        raise ValueError(f"unsupported inventory quantity fields: {', '.join(sorted(unknown_fields))}")
    amounts = {field: _quantity(quantities.get(field), field) for field in QUANTITY_FIELDS}
    if not isinstance(source_payload, (dict, type(None))):
        raise ValueError("source_payload must be a JSON object")
    payload = dict(source_payload or {})
    columns = ",".join(QUANTITY_FIELDS)
    placeholders = ",".join(["%s"] * len(QUANTITY_FIELDS))
    with conn.cursor() as cur:
        cur.execute(
            f"""insert into inventory_position_snapshot
                 (tenant_id,location_id,sku,source_type,source_provider_id,source_reference,observed_at,
                  freshness_state,{columns},expected_available_at,currency,source_payload)
               values (%s,%s,%s,%s,%s,%s,%s,%s,{placeholders},%s,%s,%s)
               on conflict (tenant_id,source_type,source_reference,location_id,sku,observed_at)
               do nothing returning id::text""",
            (tenant, location, item, source_type, source_provider_id, reference, observed_at,
             freshness_state, *(amounts[field] for field in QUANTITY_FIELDS),
             expected_available_at, currency, payload),
        )
        row = cur.fetchone()
        if row:
            return row["id"], True
        cur.execute(
            """select id::text from inventory_position_snapshot where tenant_id=%s
                 and source_type=%s and source_reference=%s and location_id=%s and sku=%s and observed_at=%s""",
            (tenant, source_type, reference, location, item, observed_at),
        )
        duplicate = cur.fetchone()
    if not duplicate:
        raise RuntimeError("duplicate inventory snapshot could not be resolved")
    return duplicate["id"], False
