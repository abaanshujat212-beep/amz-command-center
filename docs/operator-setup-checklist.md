# Operator setup checklist

Status as of 24 November 2026. The owner reports that an Ads profile is available.
Availability is not yet captured live verification. Do not paste credentials into
chat, issues, commits or this document.

## Please confirm these items

| Area | What to confirm or supply securely | Completion evidence |
| --- | --- | --- |
| Amazon Ads | Authorized GB/GBP profile, application consent and local/vault credential configuration | Profile discovery, refresh and report retrieval against the intended account |
| SP-API | Seller authorization, UK marketplace, required report/inventory roles and whether credentials are sandbox or production | Successful supported report flow and scoped source data |
| Product economics | SKU/ASIN mapping, effective dated costs, fees, VAT and currency | Imported costs and reconciled contribution figures; unknown values stay missing |
| Reconciliation | Seller Central/Ads exports covering the same dates, currency and attribution definitions | Saved comparison with explained variances |
| Rank/SOV and market data | Selected licensed provider, UK coverage, permitted usage and account availability | Reviewed contract, sanitized payload examples and provenance; no provider is selected automatically |
| Marketing Stream | Whether the advertiser is eligible and an authorized delivery destination is configured | Real messages with source timestamps, replay and duplicate tests |
| AMC / DSP | Whether an authorized instance/account exists and the intended use case | Independent access/capability review; optional expansion, not required for basic PPC |
| AI | Chosen provider/model, allowed data egress, secret-manager location and monthly ceiling | Mock tests first, then an explicitly requested small authenticated smoke call |
| Hosting | Host choice, domain, HTTPS, database, storage, email service and backup destination | Deployment, restore drill and scoped operational access |

Reply with availability, provider/host names and non-secret account references.
Store keys in the deployment secret manager or the project's ignored local
configuration. Existing Amazon refresh-token storage uses the encrypted vault.

## Codex access to this application's settings

The application has its own platform keys under **Settings → API keys**. These
are separate from OpenAI API keys, Amazon tokens and your application password.

The scoped company-settings API accepts:

- `GET /api/settings/company` with `settings:read`.
- `PATCH /api/settings/company` with `settings:write` and the exact `If-Match`
  revision returned by GET.
- Both require `Authorization: Bearer <platform-key>` and `X-Tenant-ID`.
- Create a dedicated key with only `settings:read` and, when editing is desired,
  `settings:write`. Existing generic `read`/`write` keys do not inherit these
  scopes. Keep its value in an environment secret such as `AXATY_API_KEY`.
- The issuing user's current owner/admin membership and active tenant status
  are rechecked on every request. Revoking the key or removing that access
  disables it. Only company display name and reporting timezone are editable.
- PATCH sends both fields, for example `{"name":"Example Company","timezone":"Europe/London"}`.
  Read first, review the intended values, then update with the returned revision.
  A 412 means another edit occurred: read again and review, never blindly retry.
- Changes and the key identifier are audited. Secrets, Amazon connection values,
  live-mode switches, bid/budget limits and membership changes are not exposed.

An API key alone does not install a Codex tool. The app's MCP adapter is still
unimplemented. Codex supports MCP connections, but this endpoint is ordinary
HTTP JSON, not an MCP URL. Do not register `/api/settings/company` as an MCP
server. A future adapter must reuse this authorization and narrow field list.
Local authorized CLI/API use can call the endpoint when the web app is running;
this code-only work does not start it or create a real account key.

Official reference: [Codex MCP documentation](https://developers.openai.com/codex/mcp).
