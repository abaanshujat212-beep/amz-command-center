# AXATY Amazon Command Center

Multi-tenant Amazon **SP-API + Ads API** analytics, PPC rules engine and action engine.
Marketplace: **Amazon UK** (`A1F83G8C2ARO7P`), currency **GBP**. Local-first, Hetzner later.

Product hunting, product analytics, PPC command center, PPC analytics, optimization and
reporting in one automated system — instead of Google Sheets plus manual bid changes.

---

## Status: honest version

> **Nothing in this repository has ever been executed.** No `make up`, no `make migrate`,
> no `pytest`, no `dbt build`. Every line below marked *committed* means the code exists and
> has been read; it does **not** mean it works.
>
> **32 issues open, 0 closed.**

| Layer | State | Evidence |
| --- | --- | --- |
| Compose stack (Postgres 16, Redis, Metabase) | committed, never started | `infra/docker-compose.yml` |
| Migrations `0001`–`0006` + matching `down/` | committed, never applied | `packages/db/migrations/` |
| Migration runner + ledger + checksums | committed, never run | `packages/db/migrate.py` |
| Multi-tenancy + RLS policies | committed, never proven | `tests/test_rls_isolation.py` (never run) |
| dbt project: 7 staging + 5 mart models | committed, never compiled | `packages/dbt/models/` |
| Rules engine: 11 rules, compiler, guardrails | committed, never evaluated | `services/rules/` |
| Action state machine | committed, never exercised | `services/actions/state_machine.py` |
| Amazon clients (SP-API, Ads API) | committed, never authenticated | `services/ingest/clients/` |
| Ads daily pipeline (plan/backfill logic) | committed, never fetched a byte | `services/ingest/pipelines/ads_daily.py` |
| Test suite: 8 files | committed, **never run** | `tests/` |
| Web dashboard | two helper files only | `apps/web/lib/` |
| API layer, mobile app, scheduler, CI | not started | issues #15–#18, #24 |

### The one command that changes this

```bash
make up && make migrate && make migrate-status
make seed
make testdb && make migrate-test
pytest
cd packages/dbt && dbt build
```

Running a second `make migrate` must print `nothing to do: 6 migrations already applied` —
that is the idempotency proof, not a nicety. This command is the closure gate for
**#1, #2, #3, #19, #21, #27, #28, #29**.

`dbt build` will fail on the placement models until `raw_ads_sp_placement_daily` exists
(that is #9, ingestion). For #27 the only question is whether the SQL *compiles*.

### Closure rule (enforced by #31)

Code pushed **is not** done. An issue closes only when:

1. its gate command has actually been run,
2. the real output is pasted into an issue comment,
3. every acceptance checkbox is ticked.

A closure found without its gate gets reopened.

---

## Architecture

```
Amazon SP-API + Ads API
        |
        v
services/ingest      dlt pipelines, one report kind per dataset, oldest day first
        |
        v
raw.*                landing tables, append-only, loaded_at stamped
        |
        v
packages/dbt         staging  -> deduped, renamed, percentages normalised
                     marts    -> ACOS / ROAS / CTR / CVR / CPC / TACoS + break-even
        |
        v
services/rules       SQL-compiled JSONB rules -> rule_evaluation (every match, even blocked)
        |
        v
services/actions     pending -> approved -> applied -> verified | rolled_back
        |
        v
Amazon write-back    dry-run by default, human approval, before_value re-read at apply time
```

Two things in that chain are deliberate and easy to get wrong:

- **Every match is written to `rule_evaluation`, including blocked ones.** A rule that was
  silently skipped is indistinguishable from a rule that found nothing, unless you log both.
- **`before_value` is re-read live at apply time.** If Amazon's current value no longer matches
  what the proposal was based on, the action FAILS with `drift:` rather than overwriting a
  human's change.

---

## Repo layout

```
apps/web/lib          db + format helpers (the dashboard itself is #15/#16)
services/ingest       clients/ (sp_api, ads_api), pipelines/ (ads_daily), security/
services/rules        starter_rules, diagnostic_rules, rule_catalog,
                      compiler, query, guardrails, engine
services/actions      state_machine
packages/db           migrations/ (0001-0006) + down/, migrate.py, seed.py
packages/dbt          staging + marts models, schema tests, sources
packages/shared       marketplaces.py
infra                 docker-compose.yml
docs/adr              architecture decision records
tests                 8 test files, none executed yet
```

Not yet created: `apps/api`, `apps/mobile`, `services/copilot` (#33), `.github/workflows` (#35).

---

## The rules layer

**11 rules in one catalog** (`services/rules/rule_catalog.py`), all shipping
`enabled=False, dry_run=True`:

- **7 change rules** — `scale_winners_budget`, `raise_bid_profitable`,
  `lower_bid_unprofitable`, `pause_zero_order_keyword`, `negate_wasteful_search_term`,
  `harvest_converting_search_term`, `rescue_impression_starved`
- **4 diagnostic rules** (`action_type='flag'`, report-only, DB-enforced to never apply) —
  `flag_low_ctr_listing`, `flag_low_cvr_detail_page`, `flag_above_break_even`,
  `flag_low_cvr_placement`

A rule is **data, not code**: JSONB condition compiled to SQL against a mart, with a metric
allowlist, depth and node caps. `flag` actions are asserted inert — carrying a mutation key
like `delta_pct` on a diagnostic raises at compile time.

**Guardrail order** (`services/rules/guardrails.py`): diagnostic short-circuit → kill switch →
dry-run → data quality (staleness, settlement, thin data) → cooldown → blast radius →
daily change limit → clamp → bounds → daily budget cap.

Every percentage rule reads its base from the mart and **refuses on NULL rather than assuming
zero**. This is why `placement_modifier_pct` is deliberately NULL until #32 ingests campaign
placement config — a `-20%` applied on top of a client's unseen `+50%` is not a small bid
change, it is the erasure of their decision.

---

## Hard constraints (read before coding)

- **Ads API reports go back ~95 days only** (Sponsored Display and SB v2: 60 days). Un-ingested
  days are permanently lost. Ingestion runs daily, no exceptions, and the first run is a
  one-time 95-day backfill.
- **SP-API self-authorization requires the Primary User** of the Seller Central account.
- **SP-API authorization expires after 12 months**; refresh tokens expire after one year.
  `amazon_connection.authorization_expires_at` must be tracked and alerted on.
- **No AI/ML bidding.** Amazon's March 2026 Business Solutions Agreement update restricts it
  for third-party tools. Rules are deterministic, inspectable and logged — and the System
  Copilot (#33) explains and drafts, it never decides a bid.
- **Amazon rate limits are per-endpoint and unforgiving**: Reports 0.0222 RPS (burst 10),
  Sales & Traffic max 3 requests / 5 minutes. Backoff honours `Retry-After`.
- Write-back stays dry-run / approval-only on any client account until guardrails are
  verified against a real run.
- **Secrets never enter this repo.** `.env` is gitignored; only `.env.example` is committed.
  Log redaction covers `Atzr|`, `Atza|` and client-secret patterns.
- **`sku_cost_ledger` gates the entire economics layer.** Without COGS, freight, FBA fee,
  storage and VAT, `break_even_acos` is NULL and profitability rules go quiet instead of
  failing loudly (#14).

---

## Getting started

```bash
cp .env.example .env    # fill in real values locally, never commit
make up                 # postgres + redis + metabase
make migrate            # apply packages/db/migrations in order, with checksum ledger
make seed               # dev tenants + the 11 rules, all disabled
make test               # pytest
make dbt                # dbt build
```

`make help` lists every target. Postgres-backed tests skip silently without
`TEST_DATABASE_URL` — if `pytest` reports suspiciously few tests, that is why.

---

## Decision records

| ADR | Decision |
| --- | --- |
| [001](docs/adr/001-multi-tenancy.md) | Shared schema + `tenant_id` + RLS with `FORCE ROW LEVEL SECURITY` |
| [002](docs/adr/002-rules-as-data.md) | Rules are JSONB data compiled to SQL, not Python code |
| [003](docs/adr/003-migrations.md) | Hand-rolled Python migration runner with a checksum ledger |
| [004](docs/adr/004-diagnostics.md) | Diagnostics live in `action` as `action_type='flag'`, not in a separate table |
| [005](docs/adr/005-placement-scope.md) | Placement is a diagnosis-only scope until bidding config is ingested |

---

## Milestones

| | Milestone | Gate |
| --- | --- | --- |
| M0 | Foundation (#1–#6) | RLS isolation test passes |
| M1 | Data spine (#7–#11) | 30-day backfill with no duplicates |
| M2 | Truth layer (#12–#14) | Marts within ±2% of Seller Central |
| M3 | Dashboard (#15–#18) | 7 days with no manual run |
| M4 | Rules (#19–#21, #27, #28) | 2 weeks dry-run, 70%+ suggestions correct |
| M5 | Write-back (#22–#23, #32) | 20 actions applied, 0 unwanted change |
| M6 | Mobile (#24) | Approve from phone and verify |
| M7 | Hunting (#25–#26) | 10 candidates, 3 shortlisted |
| M8 | Platform hardening (#33–#38) | Copilot answers from the live system; CI green |

#31 is the standing audit issue: plan versus reality, updated whenever either changes.
