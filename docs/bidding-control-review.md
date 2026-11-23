# Bidding control review

Campaign details show the latest tenant-scoped Amazon evidence and whether keeping native control is required. A verified dynamic strategy with neither rule-based bidding nor cost control active can be proposed for **dry-run** review of a switch to fixed bidding. The planned owner label means eligible to consider a separate managed-bid proposal, not that the application assumes control.

- No evidence, stale/unknown strategies, fixed bidding, or active/unknown cost or rule-based control cannot enter review.
- An owner or admin supplies a reason. A different owner or admin must approve that exact evidence snapshot. A newer snapshot or an expired snapshot makes the review unavailable until re-proposed against the current evidence.
- Proposal and decision are stored only as `bidding_control.review_proposed` and `bidding_control.review_approved` audit events. These are not executable action rows. Neither operation calls Amazon, changes a bid, changes placement/budget/schedules, or approves, retries, or unblocks an existing bid action. The native-control guard still governs actual proposals and worker dispatch.
- The audit records contain before, hypothetical after, actors, evidence IDs, and explicit `applied:false`. The app deliberately offers no live apply for a control transfer.
