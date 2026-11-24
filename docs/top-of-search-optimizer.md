# Top-of-Search review planner (R09.3)

The planner is proposal-only. It does not activate a strategy, insert actions,
change campaign settings, approve actions, or initiate Amazon requests.

## Input and decision contract

- Configure immutable, explicit keyword IDs in one tenant, Ads profile and
  currency. The Top-of-Search share goal and ACoS inputs are fractions, not
  percentage points. The campaign placement modifier uses integer percentage
  points. The proposal contract uses the existing `PLACEMENT_TOP` enum.
- Provide a settled, timestamped, same-profile/report-window snapshot:
  keyword Top-of-Search impression share; keyword and keyword-attributed
  Top-of-Search spend/sales; Top-of-Search clicks, impressions and orders;
  campaign budget and peak daily campaign spend; peak daily keyword clicks;
  current base bid, placement modifiers and break-even ACoS. Reported
  share is not a placement's fraction of campaign impressions.
- Native-control checks must evaluate each candidate against the trusted
  campaign state, and supply affirmative decisions independently. Unknown
  ownership never permits a candidate. No override or transfer is performed.
- Keyword and placement candidates remain separately reviewable. Campaign
  placement candidates require proof this keyword is the campaign's **only**
  enabled target across all ad groups (including auto/product targets). Null,
  partial or stale inventory never qualifies.
- The smaller of policy ACoS and break-even ACoS bounds observed keyword and
  Top-of-Search ACoS. Top-of-Search sales per click times that ceiling bounds
  the combined effective Top-of-Search bid. The daily spend stress scenario
  assumes the observed peak keyword click volume and the full bid increase
  translates to CPC, including the largest other placement modifier. The
  increment must fit both configured incremental spend and unspent campaign
  budget under the observed peak. This scenario is not a future spend or
  auction-performance guarantee. Both candidates together are checked against
  the cap, not just in isolation.
- Review serialization reuses the existing recommendation taxonomy,
  confidence and risk. Output is explicitly non-executable. The placement
  approval capability remains false; flagging or reviewing a proposal does
  not change capability status.

## Remaining integration gates

Current `mart_ppc_keyword_daily` exposes a keyword's TOS impression share,
but `mart_ppc_placement_daily` groups performance by campaign and placement,
not keyword. Do not join those totals to each keyword in a multi-target
campaign. A trusted source for keyword-by-placement paid performance, or
complete, current target-inventory evidence and same-profile/day closure
showing a single enabled target for the *entire* attribution window, is
needed before enabling ingestion. The intended DB/UI source must also carry
complete economics, currency and consistent as-of metadata.

A future integration should resolve the explicitly opted-in strategy
version, use authenticated/tenant-filtered views, call the shared native
guard with current per-action evidence, and persist through the existing
`rule_evaluation` / recommendation-evidence / approval path, not a parallel
queue. It must confirm campaign target membership and settlement at approval,
recheck native ownership, current equality/drift, approved independent/joint
caps and conflict/cooldown guards, and independently verify Amazon capability
and marketplace support. External live tests require an authorized Ads profile;
synthetic readiness never unlocks the worker. Profile configuration,
scheduler, services, and production settings are untouched in this slice.

## Offline audience-adjusted ceiling

The planner requires an explicit effective Top-of-Search bid ceiling, separate
from the base-bid cap. The current fixture supports only normalized fixed-bid
Sponsored Products evidence in GB/GBP. This is not proof that a particular
advertiser or Amazon API version supplies the evidence. Dynamic up/down,
unsupported scope, missing, stale or incomplete audience inventory all block
this estimate rather than assuming a zero boost. An explicitly complete empty
audience inventory is the only empty case that implies no audience adjustment.

If multiple adjustments are represented in a fixture, use only the highest
possible audience increase, not the sum or product of audiences. Combine it
with the selected placement factor, including for other-placement cost stress.
Compare the unrounded combined exposure with the ceiling. For example, a £1.00
bid with +50% Top-of-Search and +60% audience can reach £2.40, not £1.50. A £2.00
cap must block that combination; a proposed placement increase can be reduced
to +25% when the remaining policy and economic limits permit. Amazon currently
documents different audience-selection limits outside the US and video boosts
in the US; this fixture does not infer entitlement or model US video.

Review serialization requires the same complete scoped snapshot, including its
source revision and conditions, before its policy expiry. Changed or unavailable
evidence must be replanned even if the largest numeric boost is unchanged.
Existing native bid/placement permission checks remain in force. No account
reads, approval/apply hooks, new data source, or Amazon writes are introduced.

Source: [Amazon Sponsored Products bid adjustments](https://advertising.amazon.com/help/GYYZVM7LGSRYGWV5).
