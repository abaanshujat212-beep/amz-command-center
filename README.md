# AXATY Amazon Command Center

Multi-tenant Amazon **SP-API + Ads API** analytics, PPC rules engine and action engine.
Marketplace: **Amazon UK** (`A1F83G8C2ARO7P`), currency **GBP**. Local-first, Hetzner later.

## Why this exists

Product hunting, product analytics, PPC command center, PPC analytics, optimization and reporting
in one automated system — instead of Google Sheets + manual bid changes.

## Modules

| Module | What it does |
| --- | --- |
| Ingest | dlt pipelines: Ads API reports, SP-API Sales & Traffic, Keepa (later) |
| Warehouse | Postgres 16, `tenant_id` + RLS on every fact table |
| Marts | dbt-core: staging -> intermediate -> marts (ACOS, ROAS, CTR, CVR, TACoS) |
| Rules | JSONB rule definitions evaluated in SQL, dry-run first |
| Actions | `pending -> approved -> applied -> verified -> rolled_back` with full audit |
| Web | Next.js 15 + shadcn dashboard, Better Auth, tenant switcher |
| Mobile | Expo / React Native APK (Phase 6) |

## Repo layout

```
apps/web           Next.js dashboard
apps/api           API layer
services/ingest    dlt pipelines (sp_api, ads_api, keepa)
services/rules     rules engine
services/actions   action engine + write-back
packages/db        SQL migrations + RLS policies
packages/dbt       dbt project
packages/shared    shared helpers (marketplaces, types)
infra/             docker-compose, Makefile
docs/adr/          architecture decision records
```

## Hard constraints (read before coding)

- **Ads API reports go back ~95 days only** (Sponsored Display and SB v2: 60 days). Un-ingested days are
  permanently lost — ingestion runs daily, no exceptions.
- **SP-API self-authorization requires the Primary User** of the Seller Central account.
- **SP-API authorization expires after 12 months** — `amazon_connection.authorization_expires_at` must be tracked and alerted.
- **No AI/ML bidding.** Amazon's March 2026 Business Solutions Agreement update restricts it for third-party
  tools. Rules are deterministic, inspectable and logged.
- Write-back stays dry-run / approval-only on any client account until guardrails are merged and verified.
- Secrets never enter this repo. `.env` is gitignored; only `.env.example` is committed.

## Getting started

```bash
cp .env.example .env    # fill in real values locally, never commit
make up                 # postgres + redis + metabase
make migrate            # apply packages/db migrations
```

## Status

Phase 0 — foundation. See the issue tracker for milestones M0-M7.
