# Purchase-order receiving (offline review only)

Builds on the single-line internal PO and the inventory-location contract. The
pure service `services.inventory.purchase_receipt_review.review_receipt` returns
an auditable candidate event, or the original event for an exact replay. It
does not write to inventory, accounting, receipt storage or any vendor system.

Supply the authenticated tenant, issued PO, active inventory location, an
explicitly reviewed PO supplier-to-sellable SKU mapping in the location's
marketplace, and the trusted per-order review history. Missing or conflicting
scope (including locations lacking a marketplace) is unavailable in this
slice. Use bounded opaque internal references, not customer data or secrets.
The order currency remains explicit; this review has no valuation.

Accepted and damaged are disjoint quantities, fixed-point at four decimals.
Both use up the maximum physical quantity on the PO; damaged units are not
sellable and must include an evidence reference. Replacements, corrections,
reject/return accounting and re-opening are not supported. Cumulative totals
cover all locations for the PO. Retry by the same reviewed ID and source
reference with identical canonical data; a changed amount, actor, destination,
evidence or timestamp conflicts. Reusing a source reference with a new ID is
not another receipt. Use one source reference per discrete receipt evidence
item within the PO. Retry returns the original event and current totals.

The digest detects changed serialized evidence; it is not a signature or a
substitute for authenticated event storage. Future persistence must resolve
tenant/role and current entity records server-side, validate source-time
chronology, serialize on the order, read its full history and atomically store
the immutable event with tenant/PO-linked keys, unique IDs and source refs.
Roll out receipt adjustments and reversal rules before any inventory or landed
cost posting. No review output can be treated as an inventory snapshot or a
COGS/freight entry.
