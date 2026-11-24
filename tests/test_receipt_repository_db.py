import os
import re
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from services.inventory.purchase_receipt_review import ReceiptObservation, ReceiptReviewError
from services.inventory.receipt_repository import save_receipt_review

pytestmark = pytest.mark.db
URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


@pytest.fixture
def context():
    with psycopg.connect(URL, row_factory=dict_row) as db:
        tenant, actor, order = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Receipt test',%s)", (tenant, str(tenant)))
        db.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')", (tenant, actor))
        party = db.execute("insert into party(tenant_id,party_kind,display_name,normalized_name) values(%s,'organization','Factory','factory') returning id", (tenant,)).fetchone()["id"]
        db.execute("insert into supplier_profile(tenant_id,party_id) values(%s,%s)", (tenant, party))
        product = db.execute("insert into supplier_product(tenant_id,supplier_party_id,sku,product_name) values(%s,%s,'SUP-1','Widget') returning id", (tenant, party)).fetchone()["id"]
        quote = db.execute("insert into supplier_quote(tenant_id,supplier_party_id,supplier_product_id,quote_ref,version,quoted_on,currency,unit_price) values(%s,%s,%s,'Q1',1,current_date,'GBP',2) returning id", (tenant, party, product)).fetchone()["id"]
        db.execute("""insert into supplier_purchase_order(id,tenant_id,quote_id,supplier_name,product_sku,
            product_name,quote_ref,quote_version,currency,unit_price,quantity,created_by,state)
            values(%s,%s,%s,'Factory','SUP-1','Widget','Q1',1,'GBP',2,10,%s,'issued')""", (order, tenant, quote, actor))
        location = db.execute("""insert into inventory_location(tenant_id,location_code,location_type,display_name,marketplace_id)
            values(%s,'warehouse','own_warehouse','Warehouse','UK') returning id""", (tenant,)).fetchone()["id"]
        db.execute("set local role axaty_app")
        db.execute("select set_tenant(%s)", (tenant,))
        observation = ReceiptObservation(uuid.uuid4(), actor, location, "SELL-1", "delivery-1",
                                         datetime.now(timezone.utc), "4", "1", "damage-photo-1")
        yield db, dict(tenant_id=tenant, actor_id=actor, order_id=order,
                      observation=observation, mapping_evidence_ref="reviewed-map-1")
        db.rollback()


def test_split_receipts_replay_and_audit_are_atomic(context):
    db, args = context
    first = save_receipt_review(db, **args)
    assert first.outstanding_units == 50000
    assert save_receipt_review(db, **args).replay
    second = replace(args["observation"], review_id=uuid.uuid4(), source_ref="delivery-2",
                     accepted="5", damaged="0", damage_evidence_ref=None)
    final = save_receipt_review(db, **{**args, "observation": second})
    assert final.outstanding_units == 0
    assert db.execute("select count(*) n from purchase_receipt_review").fetchone()["n"] == 2
    assert db.execute("select count(*) n from audit_log where action='supplier.receipt.reviewed'").fetchone()["n"] == 2
    assert db.execute("select count(*) n from inventory_position_snapshot").fetchone()["n"] == 0


def test_over_receipt_and_changed_replay_leave_no_partial_writes(context):
    db, args = context
    save_receipt_review(db, **args)
    for changes in ({"accepted": "3"}, {"review_id": uuid.uuid4(), "source_ref": "delivery-2", "accepted": "6"}):
        with pytest.raises(ReceiptReviewError):
            save_receipt_review(db, **{**args, "observation": replace(args["observation"], **changes)})
    assert db.execute("select count(*) n from purchase_receipt_review").fetchone()["n"] == 1


def test_membership_actor_and_chronology_fail_closed(context):
    db, args = context
    for changes in ({"actor_id": uuid.uuid4()}, {"observed_at": datetime.now(timezone.utc) + timedelta(days=1)},
                    {"observed_at": datetime(2000, 1, 1, tzinfo=timezone.utc)}):
        with pytest.raises(ReceiptReviewError):
            save_receipt_review(db, **{**args, "observation": replace(args["observation"], **changes)})
    db.execute("update tenant_member set role='viewer' where tenant_id=%s", (args["tenant_id"],))
    with pytest.raises(ReceiptReviewError, match="owners and admins"):
        save_receipt_review(db, **args)


def test_receipt_rls_and_immutable_permissions(context):
    db, args = context
    save_receipt_review(db, **args)
    assert not db.execute("select has_table_privilege(current_user,'purchase_receipt_review','UPDATE') allowed").fetchone()["allowed"]
    assert not db.execute("select has_table_privilege(current_user,'purchase_receipt_review','DELETE') allowed").fetchone()["allowed"]
    db.execute("select set_tenant(%s)", (uuid.uuid4(),))
    assert db.execute("select count(*) n from purchase_receipt_review").fetchone()["n"] == 0
    with pytest.raises(ReceiptReviewError):
        save_receipt_review(db, **args)


def test_audit_failure_rolls_back_receipt(context):
    db, args = context
    db.execute("reset role")
    db.execute("revoke insert on audit_log from axaty_app")
    db.execute("set local role axaty_app")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        save_receipt_review(db, **args)
    assert db.execute("select count(*) n from purchase_receipt_review").fetchone()["n"] == 0


def test_cancelled_order_accepts_only_exact_existing_retry(context):
    db, args = context
    save_receipt_review(db, **args)
    db.execute("update supplier_purchase_order set state='cancelled' where id=%s", (args["order_id"],))
    assert save_receipt_review(db, **args).replay
    with pytest.raises(ReceiptReviewError, match="issued order"):
        save_receipt_review(db, **{**args, "observation": replace(args["observation"],
            review_id=uuid.uuid4(), source_ref="new-delivery")})


def test_web_queries_read_persisted_receipts_without_cross_tenant_access(context):
    db, args = context
    source = (Path(__file__).parents[1] / "apps/web/lib/receipt-history.ts").read_text(encoding="utf-8")
    def run(name, tenant):
        sql = re.search(rf"export const {name} = `(.*?)`", source, re.S).group(1)
        sql = sql.replace("$1", "%(tenant)s").replace("$2", "%(order)s")
        return db.execute(sql, {"tenant": tenant, "order": args["order_id"]}).fetchall()
    empty = run("RECEIPT_SUMMARY_SQL", args["tenant_id"])[0]
    assert float(empty["outstanding"]) == 10
    assert empty["review_count"] == 0
    save_receipt_review(db, **args)
    summary = run("RECEIPT_SUMMARY_SQL", args["tenant_id"])[0]
    assert float(summary["accepted"]) == 4
    assert float(summary["damaged"]) == 1
    assert float(summary["outstanding"]) == 5
    history = run("RECEIPT_HISTORY_SQL", args["tenant_id"])
    assert len(history) == 1
    assert history[0]["sellable_sku"] == "SELL-1"
    assert run("RECEIPT_HISTORY_SQL", uuid.uuid4()) == []
    db.execute("select set_tenant(%s)", (uuid.uuid4(),))
    assert run("RECEIPT_SUMMARY_SQL", args["tenant_id"]) == []
    assert run("RECEIPT_HISTORY_SQL", args["tenant_id"]) == []
