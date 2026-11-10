# Live negative keyword actions

Approved search-term actions may create negative exact or negative phrase
keywords at one unambiguous campaign or ad-group destination. The rules query
retains source campaign/ad-group identifiers and their distinct counts; the
proposal is blocked when the term spans multiple destinations. The action
payload retains the source term and identifiers for audit.

The live worker performs a destination-scoped duplicate/conflict read directly
before the create call. Both negative action types require their explicit
confirmation phrase and have no rollback capability. Provider create calls are
not automatically retried after an ambiguous result; an operator must
re-evaluate the destination before retrying. Campaign budgets, approval state,
and other guardrails are still checked by the existing worker before loading
Ads credentials.

Only negative exact and phrase keyword actions are enabled here. Negative
product-target creation remains unsupported until its provider payload and
destination-specific duplicate contract are verified; the capability registry
continues to fail closed for it.
