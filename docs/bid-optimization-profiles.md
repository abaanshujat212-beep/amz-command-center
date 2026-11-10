# Bid optimization profiles

Strategy versions may set `settings.bid_optimization_profile` to one of
`VERY_CONSERVATIVE`, `CONSERVATIVE`, `BALANCED`, `AGGRESSIVE`,
`VERY_AGGRESSIVE`, or `CUSTOM`. The profile resolver returns an inspectable
`profile_version` and normalized values; store the selection in the immutable
`strategy_version.settings` JSON so each run can retain the versioned strategy
snapshot. Missing profile settings resolve to `VERY_CONSERVATIVE` for existing
tenants.

Custom strategies provide the complete `settings.bid_optimization_custom`
object with `max_change_pct`, `min_clicks`, `min_impressions`,
`max_data_age_days`, and `cooldown_days`. Unknown or missing fields, non-finite
changes, and out-of-range values fail closed. Platform limits cap the maximum
step at 30%, minimum evidence at 5 clicks and 25 impressions, maximum evidence
age at seven days, and cooldown at 90 days. Profiles never relax tighter tenant
guardrails. The resolved cooldown remains configuration for the existing
cooldown gate; the bid calculation itself does not authorize or execute edits.
