# Client onboarding — Path A (client is the Seller Central primary user)

**Confirmed 20 Aug 2026:** the client is the primary account holder of their own
Seller Central account. That unlocks Path A, which is the fast route.

## Why Path A matters

| | Path A (this one) | Path B (public developer app) |
| --- | --- | --- |
| Who registers the app | The client, in their own account | Us |
| Amazon review | None — private app, self-authorised | Website + architecture + data-protection review |
| Realistic time | Same day to a few days | Several weeks |
| Works for more clients later | One registration per client | One app, many clients |

We start on Path A now and only move to Path B when a client cannot or will not
register an app themselves.

> **Never ask for the client's password, and never accept it.** Sharing Seller
> Central credentials violates Amazon's terms and puts their account at risk. We
> only ever need a *refresh token*, which they generate themselves and can revoke
> at any time.

## What we need from the client (SP-API)

Send them these steps. Everything happens inside **their** account.

1. Seller Central → **Apps & Services → Develop Apps** (Developer Central)
2. Register as a **private developer** — this is a form about *their* own use,
   not a public app submission
3. **Add app client** with these details:
   - App name: `AXATY Command Center`
   - Roles: **Selling Partner Insights**, **Inventory and Order Tracking**,
     **Amazon Fulfilment**, **Brand Analytics** (they are Brand Registered, so
     Brand Analytics unlocks Search Query Performance later)
   - Do **not** request PII roles. We do not need customer names or addresses,
     and requesting them triggers extra review for no benefit.
4. On the app row → **Authorise** → self-authorisation → generates a
   **refresh token**
5. They send us three values, over a password manager or an encrypted note —
   not WhatsApp, not email:
   - `LWA client ID`
   - `LWA client secret`
   - `SP-API refresh token`

## What we handle ourselves (Ads API)

The Ads API works differently and stays on our side permanently:

1. We apply once at <https://advertising.amazon.com/partner-network/register-api>
   (approval is typically up to ~72 hours, judged on our application, not on the
   client's account age)
2. We create **one** LWA application for our company
3. For each client, they click a consent link once → we receive a refresh token
   for their advertiser account
4. `GET /v2/profiles` gives us their UK profile
   (`countryCode: GB`, `currencyCode: GBP`)

So: **SP-API = one registration per client. Ads API = one app, many clients.**

## Two things to say to the client honestly

1. **Account age does not speed up approval.** A 5–6 year old account is great
   for data quality and trust, but Amazon judges the *application*, not the
   account's age. Do not promise a faster timeline because the account is old.

2. **Their history is mostly not retrievable.** This is the one that surprises
   people. Amazon's Ads reporting API only serves roughly the last **95 days**
   (60 for Sponsored Display and SB v2). Six years of advertising history does
   **not** come back. Sales data via SP-API goes back ~2 years, but ad spend does
   not.

   Practical consequence: **the day credentials arrive, we run the 95-day
   backfill.** Every day we wait is a day permanently lost. This is why issues
   #7 and #8 are the only blockers worth chasing daily.

## The 12-month trap

Seller developer authorisations must be re-confirmed **every 12 months** or the
connection is suspended. Amazon emails a warning 30 days before.

We do not rely on that email. `amazon_connection.authorization_expires_at` is
stored at connection time, and an `auth_expiring` alert fires at 30 / 14 / 3
days. A silently dead connection means a silent gap in the data, and a gap in the
data means rules acting on a stale picture.

## Onboarding checklist

- [ ] Client registers private developer app and self-authorises (above)
- [ ] Credentials received via password manager, stored through the token vault
      (envelope-encrypted, `key_version` recorded), never in `.env` in production
- [ ] `amazon_connection` row created, `authorization_expires_at` set to +12 months
- [ ] `GET /v2/profiles` returns the UK profile — confirms the Ads consent worked
- [ ] **95-day Ads backfill run the same day**
- [ ] Sales & Traffic backfill (CHILD ASIN granularity)
- [ ] `sku_cost_ledger` filled in with the client — COGS, freight, fees, VAT.
      Without this there is no break-even ACOS, and without break-even ACOS every
      rule is guesswork
- [ ] Rules reviewed together, still `enabled=false`, `dry_run=true`
- [ ] Two weeks of dry-run proposals reviewed before anything goes live
