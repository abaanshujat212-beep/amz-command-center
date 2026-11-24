"""Persist receiving reviews atomically; callers authenticate actor and set tenant RLS.

This boundary records human-reviewed SKU mapping evidence with the receipt.
It does not post inventory or cost, or communicate with a supplier/Amazon.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.inventory.purchase_receipt_review import (
    PurchaseOrder,
    ReceiptEvent,
    ReceiptObservation,
    ReceiptReviewError,
    ReceivingLocation,
    ReviewedSkuMapping,
    review_receipt,
)


def _encode(event):
    return {key: value.isoformat() if isinstance(value, datetime) else str(value)
            if isinstance(value, UUID) else value for key, value in asdict(event).items()}


def _decode(payload):
    values = dict(payload)
    for key in ("tenant_id", "order_id", "review_id", "actor_id", "location_id"):
        values[key] = UUID(values[key])
    values["observed_at"] = datetime.fromisoformat(values["observed_at"])
    return ReceiptEvent(**values)


def save_receipt_review(conn, *, tenant_id: UUID, actor_id: UUID, order_id: UUID,
                        observation: ReceiptObservation, mapping_evidence_ref: str):
    """Owner/admin records a reviewed mapping and receipt in one transaction.

    The actor must come from trusted authentication, never a request body.
    A PO lock serializes all receipts across locations. Exact retries return the
    existing event without another audit. The caller retains commit ownership.
    """
    if observation.actor_id != actor_id:
        raise ReceiptReviewError("receipt actor does not match authenticated actor")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""select m.role from tenant_member m join tenant t on t.id=m.tenant_id
                       where m.tenant_id=%s and m.user_id=%s and t.status='active'
                       for share of m,t""", (tenant_id, actor_id))
        member = cur.fetchone()
        if not member or member["role"] not in {"owner", "admin"}:
            raise ReceiptReviewError("only tenant owners and admins can review receipts")
        cur.execute("select * from supplier_purchase_order where tenant_id=%s and id=%s for update",
                    (tenant_id, order_id))
        order = cur.fetchone()
        cur.execute("select * from inventory_location where tenant_id=%s and id=%s for share",
                    (tenant_id, observation.location_id))
        location = cur.fetchone()
        if not order or not location:
            raise ReceiptReviewError("receipt scope is unavailable")
        now = datetime.now(timezone.utc)
        if (not isinstance(observation.observed_at, datetime)
                or observation.observed_at.utcoffset() is None
                or not order["created_at"] <= observation.observed_at <= now):
            raise ReceiptReviewError("receipt observation must fall between order creation and now")
        cur.execute("select evidence from purchase_receipt_review where tenant_id=%s and order_id=%s",
                    (tenant_id, order_id))
        history = tuple(_decode(row["evidence"]) for row in cur.fetchall())
        result = review_receipt(
            tenant_id=tenant_id,
            order=PurchaseOrder(tenant_id, order_id, order["product_sku"],
                                str(order["quantity"]), order["currency"], order["state"]),
            location=ReceivingLocation(tenant_id, location["id"], location["marketplace_id"], location["active"]),
            mapping=ReviewedSkuMapping(tenant_id, order_id, order["product_sku"],
                                       observation.sellable_sku, location["marketplace_id"], mapping_evidence_ref),
            observation=observation, prior_events=history,
        )
        if result.replay:
            return result
        event = result.event
        cur.execute("""insert into purchase_receipt_review
            (id,tenant_id,order_id,location_id,source_ref,observed_at,actor_id,evidence)
            values(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (event.review_id, tenant_id, order_id, event.location_id, event.source_ref,
             event.observed_at, actor_id, Jsonb(_encode(event))))
        cur.execute("""insert into audit_log(tenant_id,actor_user_id,action,entity,after)
            values(%s,%s,'supplier.receipt.reviewed',%s,%s)""",
            (tenant_id, actor_id, f"purchase_receipt_review:{event.review_id}",
             Jsonb({"order_id": str(order_id), "fingerprint": event.fingerprint,
                    "accepted_units": event.accepted_units, "damaged_units": event.damaged_units,
                    "inventory_posted": False, "cost_posted": False})))
        return result
