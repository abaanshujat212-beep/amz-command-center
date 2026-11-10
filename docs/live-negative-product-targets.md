# Live negative product targets

Campaign-scoped `add_negative_product` actions carry an ASIN and explicit
ad-group destination. They use the Sponsored Products `asinSameAs` negative
target expression, preflight the campaign's negative target pages, and require
the confirmation phrase `ADD NEGATIVE PRODUCT TARGET`. The capability registry
marks the action as approval-gated, verifiable, and non-reversible. The worker
will not replay an ambiguous create request; operators must re-check the Ads
account before retrying.

The ASIN is validated as ten alphanumeric characters. Unknown expression
types, unsupported action/entity combinations, and non-live readiness remain
fail-closed. No product target is created by automatic term selection; the
existing action queue and approval process are required.
