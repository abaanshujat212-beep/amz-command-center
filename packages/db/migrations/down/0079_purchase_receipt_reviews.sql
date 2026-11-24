drop table if exists purchase_receipt_review;
alter table supplier_purchase_order drop constraint if exists supplier_purchase_order_id_tenant;
