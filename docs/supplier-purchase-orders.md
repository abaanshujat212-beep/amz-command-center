# Internal supplier purchase orders

Open **Suppliers → Purchase orders**. Owners, admins and users can draft a single-line internal order from a current supplier quote. The quantity must meet the quote MOQ (or product MOQ if the quote omits it). The draft snapshots supplier/product labels, SKU, quote/version, currency and unit price; the database computes the merchandise total exactly. Duplicate submission of the same draft is safe.

Owners/admins can approve prospects, then mark a draft issued internally or cancel a draft/issued record. Issuing requires an approved supplier and current quote. Role and tenant checks run on the server; transitions compare the expected prior state and write a tenant audit event in the same transaction. The history is retained.

This does not send a PO, authorize payments, post stock/COGS or accept deliveries. Multi-line procurement, landed cost allocation, split receipts and Amazon FBA shipment/discrepancy tracking remain separate work. Do not interpret internal issue as a supplier confirmation.

Migration 0078 is additive. For application rollback, keep the table and its audit records in place; the down SQL drops the new table and is for empty disposable environments or a separately reviewed data-retention plan.

Local smoke uses a fresh in-memory database and existing supplier schema DDL. It needs Node's TypeScript stripping and PGlite installed in the developer environment:
`PGLITE_MODULE=/path/to/pglite/dist/index.cjs node infra/scripts/verify_supplier_purchase_order.cjs`.
