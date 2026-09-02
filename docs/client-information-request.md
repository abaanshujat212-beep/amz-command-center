# Amazon Command Center — Client Information & Access Request

This checklist contains everything required to connect and configure the Amazon
Command Center for a UK marketplace account.

## 1. Account and business details

Please provide:

- [ ] Legal business name
- [ ] Primary contact name, email and phone number
- [ ] Amazon Seller Central account name
- [ ] UK marketplace confirmation (`Amazon.co.uk`)
- [ ] Brand name(s)
- [ ] Brand Registry status
- [ ] List of active ASINs and SKUs, preferably as CSV/XLSX
- [ ] Preferred reporting timezone (default: `Europe/London`)
- [ ] Currency confirmation (default: GBP)

## 2. SP-API access

The Seller Central **Primary User** must create and self-authorise a private
SP-API application inside their own account.

Requested application name: `AXATY Command Center`

Requested roles:

- Selling Partner Insights
- Inventory and Order Tracking
- Amazon Fulfilment
- Brand Analytics, if the brand is registered

Do not request customer PII roles. The Command Center does not need customer
names, addresses or payment information.

After self-authorisation, securely provide:

- [ ] `SPAPI_CLIENT_ID` / LWA client ID
- [ ] `SPAPI_CLIENT_SECRET` / LWA client secret
- [ ] `SPAPI_REFRESH_TOKEN`

Marketplace configuration is already set for the UK:

- Marketplace ID: `A1F83G8C2ARO7P`
- Endpoint: `https://sellingpartnerapi-eu.amazon.com`

## 3. Amazon Ads API consent

We provide the Amazon Ads consent link. The client must:

- [ ] Open the consent link while signed into the correct Amazon account
- [ ] Review the requested advertising-management scope
- [ ] Click **Allow**
- [ ] Confirm which UK advertiser account/profile should be connected if more
      than one is listed

The client does not need to manually find the Ads profile ID. We discover the
authorised profiles through the API and select the UK/GBP profile with the
client's confirmation.

## 4. Product cost and economics data

Accurate costs are required before the system can calculate contribution
margin, profit or break-even ACOS.

For every SKU, provide a CSV/XLSX containing:

- [ ] SKU
- [ ] ASIN
- [ ] Effective date (`valid_from`)
- [ ] Product cost / COGS
- [ ] Freight-in or landed shipping cost
- [ ] Amazon referral fee percentage
- [ ] FBA fulfilment fee
- [ ] Estimated storage cost
- [ ] VAT rate
- [ ] Currency

If a value is unknown, mark it as missing instead of entering zero.

## 5. PPC targets and safety limits

Please confirm:

- [ ] Target ACOS by brand/product, or one account-wide starting target
- [ ] Minimum and maximum keyword/target bid
- [ ] Maximum allowed daily campaign budget
- [ ] Maximum bid or budget change percentage per action
      (system default cap: 25%)
- [ ] Maximum number of changes allowed per day
- [ ] Campaigns, products or keywords that must never be changed
- [ ] Seasonal events or promotion dates that affect normal performance
- [ ] Names/emails of people allowed to approve or reject recommendations

The initial connection remains `dry_run=true`. No Amazon mutation is performed
until an authorised operator explicitly approves live operation.

## 6. Reconciliation and launch validation

To compare the Command Center with Seller Central, please provide exports for an
agreed recent date range:

- [ ] Sponsored Products campaign report
- [ ] Sponsored Products search-term report
- [ ] Sponsored Products keyword/target report
- [ ] Business Reports — Sales and Traffic by Child ASIN
- [ ] Current campaign budgets and placement modifiers
- [ ] Current negative keywords, if available

These exports contain business metrics only; customer-level PII is not needed.

## 7. Operational contacts and approvals

- [ ] Primary commercial/PPC contact
- [ ] Technical or Seller Central access contact
- [ ] Emergency contact for suspected incorrect advertising changes
- [ ] Preferred alert channel
- [ ] Agreed approval SLA for pending recommendations
- [ ] Written confirmation before enabling live Ads write-back

## 8. Optional integrations

Only required if these features will be used:

- [ ] Keepa API key and agreed monthly token budget for product hunting
- [ ] Brand Registry access for Search Query Performance data
- [ ] LLM provider choice and tenant-owned API key for System Copilot
- [ ] Historical cost files or older Amazon exports

## Secure credential handoff

Credentials must be shared using a password manager, one-time secret link or an
encrypted handoff session.

Do **not** send credentials through email, WhatsApp, Slack or a spreadsheet.
Do **not** provide the Seller Central username, password or MFA code. We will
never ask for them.

The client can revoke API authorisation from Amazon at any time. SP-API seller
authorisation must also be reconfirmed periodically; the system records its
expiry and raises advance alerts.

## Go-live sequence

1. Receive credentials securely and verify the UK account/profile.
2. Run the available Ads history backfill immediately.
3. Load Sales & Traffic and cost-ledger data.
4. Reconcile dashboard totals against Seller Central exports.
5. Review recommendations in dry-run mode for at least two weeks.
6. Confirm guardrails and approval users.
7. Obtain explicit written approval before enabling live write-back.

## Short message to send the client

> Amazon Command Center setup ke liye hamein aapka Seller Central password ya
> MFA code nahi chahiye. Aap apne Seller Central account mein private SP-API app
> self-authorise karenge aur client ID, client secret aur refresh token secure
> password-manager link se share karenge. Ads account ke liye hum consent link
> bhejenge, jahan aap correct UK advertiser profile ko Allow karenge. Profit aur
> break-even ACOS ke liye SKU-wise COGS, freight, Amazon fees, FBA fee, storage
> aur VAT data bhi chahiye. System pehle minimum do haftay dry-run mein rahega;
> written approval ke baghair koi live advertising change nahi hoga.
