# AXATY Amazon Command Center

Multi-tenant Amazon **SP-API + Ads API** analytics, PPC rules engine and action engine.
Marketplace: **Amazon UK** (`A1F83G8C2ARO7P`), currency **GBP**. Local-first, Hetzner later.

Product hunting, product analytics, PPC command center, PPC analytics, optimization and
reporting in one automated system — instead of Google Sheets plus manual bid changes.

---

## Status: MVP build sprint

CI is active and has been green across the MVP implementation PRs. The repo has moved
from “committed but never executed” to a tested first-pass system with ingestion, dashboard
reads, scheduler, rules, action write-back seams, Ads HTTP dispatch, verification, operational
alerts and repeatable helper commands.

Completed MVP PRs:

| PR | Area | Result |
| --- | --- | --- |
| #42 | CI gate | Python/static tests, Postgres-backed tests and web build checks |
| #43 | Ads ingestion orchestration | Daily Ads pipeline, watermarks, run history, dry-run seam |
| #44 | Ads raw landing | Sponsored Products raw JSON landing tables + upserts |
| #45 | dbt Ads staging | Staging models aligned to raw JSON landing tables |
| #46 | SP-API Sales & Traffic | Raw CHILD-ASIN daily pipeline and staging alignment |
| #47 | Dashboard API reads | Tenant-scoped JSON endpoints for dashboard, drilldowns and history |
| #48 | Scheduler/alerts | MVP ingestion runner and stale/missing/failed data alerts |
| #49 | Rules runner | Tenant rules evaluation command seam and scheduler integration |
| #50 | Action worker seam | Approved-action worker, drift protection and dry-run default |
| #51 | Ads HTTP layer | Token refresh, catalogued dispatch, Retry-After, report polling/download |
| #52 | Ads action client | Live Ads action client behind `--live-ads`, encrypted rotated-token persistence |
| #53 | Verification scorecard | T+7 action verification with pre/post keyword performance impact |
| #68-#70 | Scheduler catch-up | Rolling gap detection plus Sales & Traffic / Ads replay seams |
| #71-#74 | Operational visibility | Run history, dashboard alert banners and persisted scheduler alerts |
| #75-#77 | Action worker observability | Failure/auth alerts and `action_worker` run summaries |
| #79-#83 | Operator workflow | Local gates, alert docs, PR batch flow and Makefile helper commands |

### Current state by layer

| Layer | State | Evidence |
| --- | --- | --- |
| Compose stack (Postgres 16, Redis, Metabase) | committed | `infra/docker-compose.yml` |
| Migrations through `0016` + matching downs for new raw tables | CI-tested | `packages/db/migrations/` |
| Migration runner + ledger + checksums | CI-tested | `packages/db/migrate.py`, `tests/test_migrate.py` |
| Multi-tenancy + RLS policies | Postgres-tested | `tests/test_rls_isolation.py` |
| dbt project: staging + marts | committed; models updated for raw JSON | `packages/dbt/models/` |
| Ads daily ingestion | implemented with live client seam and catch-up replay | `services/ingest/pipelines/ads_daily.py` |
| Sales & Traffic ingestion | implemented with live client seam and catch-up replay | `services/ingest/pipelines/sales_traffic.py` |
| Ads API client | HTTP dispatch + token refresh implemented | `services/ingest/clients/ads_api.py` |
| Rules engine | evaluated by runner, queues proposals only | `services/rules/` |
| Scheduler | runs ingestion + rules, evaluates/persists health alerts, catch-up support | `services/scheduler/runner.py` |
| Action worker | dry-run default; live Ads opt-in; alerts + run summaries | `services/actions/worker.py` |
| Verification | T+7 scorecard for keyword-level actions | `services/actions/verification.py` |
| Web dashboard | server pages, JSON read endpoints, alert/run-history visibility | `apps/web/` |
| Operator docs | local gates, alerts, PR batch flow | `docs/` |
| Test suite | CI green across Python, DB and web checks | `.github/workflows/ci.yml`, `tests/` |

### Main local gates

```bash
ruff check .
pytest -q -m "not db"

make up
python -m packages.db.migrate up
python -m packages.db.migrate up
python -m packages.db.migrate status
python -m packages.db.seed
pytest -q -m db

cd apps/web && npm install && npm run typecheck && npm run build
```

See also: `docs/local-gates.md`.

### Useful operator commands

```bash
make scheduler                  # dry-run scheduler cycle by default
make scheduler-history          # recent pipeline run history
make scheduler-catch-up         # rolling catch-up gaps
make actions                    # approved-action worker dry-run
make actions-live               # explicit live Ads write-back
```

All commands default to `DEV_TENANT_ID`; override with `TENANT_ID=<tenant-id>`.

### Still intentionally pending

- Full dbt build in CI and mart reconciliation against Seller Central.
- Real SP-API HTTP dispatch layer parity with the Ads client.
- Live baseline reads for every Ads action type before write-back.
- Campaign/placement/search-term verification scorecards beyond keyword actions.
- Cost ledger import UI/workflow for real COGS, FBA, freight, VAT and storage.
- Mobile app and product-hunting modules.

---

## Architecture

```
Amazon SP-API + Ads API
        |
        v
services/ingest      report pipelines, one report kind per dataset, oldest day first
        |
        v
raw.*                landing tables, JSON payloads, loaded_at stamped
        |
        v
packages/dbt         staging  -> deduped, renamed, percentages normalised
                     marts    -> ACOS / ROAS / CTR / CVR / CPC / TACoS + break-even
        |
        v
copilot.*            per-mart views with the tenant filter baked in
        |
        v
services/rules       SQL-compiled JSONB rules -> rule_evaluation -> pending actions
        |
        v
services/actions     pending -> approved -> applied -> verified | rolled_back
        |
        v
Amazon write-back    dry-run by default; live Ads requires explicit --live-ads
```

Three things in that chain are deliberate and easy to get wrong:

- **Every match is written to `rule_evaluation`, including blocked ones.** A rule that was
  silently skipped is indistinguishable from a rule that found nothing, unless you log both.
- **`before_value` is re-read live at apply time when the injected client provides it.** If
  Amazon's current value no longer matches what the proposal was based on, the action FAILS
  with `drift:` rather than overwriting a human's change.
- **The `marts` schema has no RLS.** Dashboard and copilot reads go through filtered views;
  services that read marts directly must pass explicit `tenant_id` predicates.

---

## Operational visibility

- Scheduler health checks persist `data_stale` and `pipeline_failed` alerts.
- Action worker failures persist `action_failed` alerts.
- Live Ads credential load failures persist `auth_expired` alerts.
- The Command Center shows critical/warning alert banners before KPI content and even in the no-data state.
- The History page shows open alerts and recent `pipeline_run` records, including `action_worker` summaries.

See also: `docs/alert-operations.md`.

---

## Repo layout

```
apps/web              Next.js 15 app router: Command Center, approvals, history,
                      JSON API reads and lib/ query helpers
services/ingest       clients/ (sp_api, ads_api), pipelines/ (ads_daily, sales_traffic), security/
services/rules        starter_rules, diagnostic_rules, compiler, query, guardrails, engine, runner
services/actions      state_machine, worker, verification
services/scheduler    MVP ingestion/rules runner + pipeline health alerts
services/copilot      system_map (generated + self-checking), sql_guard (allowlist validator)
packages/db           migrations/ + down/, migrate.py, seed.py
packages/dbt          staging + marts models, schema tests, sources
packages/shared       marketplaces.py, endpoints.py
infra                 docker-compose.yml
docs                  ADRs plus local gates, alert ops and PR batch workflow
tests                 Python unit + Postgres-backed coverage
```

---

## The rules layer

Rules are JSONB data compiled to SQL against a mart, with a metric allowlist, depth and node
caps. The engine queues proposals only; it never talks to Amazon. Applying is a separate,
approved action-worker step.

Guardrail order: diagnostic short-circuit → kill switch → dry-run → data quality → cooldown →
blast radius → daily change limit → clamp → bounds → daily budget cap.

Every percentage rule reads its base from the mart and **refuses on NULL rather than assuming
zero**. This is why `placement_modifier_pct` stays guarded until live campaign bidding config
is available.

---

## Database roles

Three roles, three blast radii. Nothing uses the owner connection except migrations and dbt.

| Role | Used by | Can read `marts` | Can write |
| --- | --- | --- | --- |
| owner (`DATABASE_URL`) | `migrate.py`, dbt, seed | yes | yes |
| `axaty_app` (`DATABASE_URL_APP`) | `apps/web`, services | no — `copilot.*` views only | yes, RLS-forced |
| `axaty_copilot` (`DATABASE_URL_COPILOT`) | system copilot | no — `copilot.*` views only | no, read-only |

`apps/web/lib/db.ts` refuses to start if `DATABASE_URL_APP` is missing or equal to `DATABASE_URL`.

---

## Hard constraints

- **Ads API reports go back ~95 days only** (Sponsored Display and SB v2: 60 days).
- **Sales & Traffic max history is 2 years** and must be requested at CHILD ASIN granularity.
- **Amazon rate limits are unforgiving**; `Retry-After` wins over local backoff.
- **Write-back is dry-run by default**. Live Ads mutation requires `--live-ads` or `make actions-live`.
- **Secrets never enter this repo.** Refresh tokens are stored encrypted; rotated tokens are
  persisted back to the vault.
- **No AI/ML bidding.** Rules are deterministic, inspectable and logged.
- **Cost ledger is required for economics.** Missing COGS/FBA/freight/VAT keeps break-even
  ACOS null and profitability rules quiet.

---

## Getting started

```bash
cp .env.example .env    # fill in real values locally, never commit
make up
python -m packages.db.migrate up
python -m packages.db.seed
pytest

cd apps/web && npm install && npm run dev
```

Useful commands:

```bash
python -m services.scheduler.runner --tenant-id <tenant-id>
python -m services.scheduler.runner --tenant-id <tenant-id> --show-history --skip-rules
python -m services.scheduler.runner --tenant-id <tenant-id> --show-catch-up --skip-rules
python -m services.rules.runner --tenant-id <tenant-id>
python -m services.actions.worker --tenant-id <tenant-id>          # dry-run default
python -m services.actions.worker --tenant-id <tenant-id> --live-ads
python -m services.actions.verification --tenant-id <tenant-id>
```

---

## Decision records

| ADR | Decision |
| --- | --- |
| [001](docs/adr/001-multi-tenancy.md) | Shared schema + `tenant_id` + RLS with `FORCE ROW LEVEL SECURITY` |
| [002](docs/adr/002-rules-as-data.md) | Rules are JSONB data compiled to SQL, not Python code |
| [003](docs/adr/003-migrations.md) | Hand-rolled Python migration runner with a checksum ledger |
| [004](docs/adr/004-diagnostics.md) | Diagnostics live in `action` as `action_type='flag'`, not in a separate table |
| [005](docs/adr/005-placement-scope.md) | Placement is a diagnosis-only scope until bidding config is ingested |
| [006](docs/adr/006-system-copilot.md) | The copilot's system map is generated and test-enforced, never hand-written |

---

## Milestones

| | Milestone | Gate |
| --- | --- | --- |
| M0 | Foundation (#1–#6) | RLS isolation test passes; Ads client unit tests green |
| M1 | Data spine (#7–#11) | Ads + Sales raw pipelines run with no duplicate rows |
| M2 | Truth layer (#12–#14) | Marts within ±2% of Seller Central |
| M3 | Dashboard (#15–#18) | Dashboard/API reads tenant-scoped and scheduler reports health |
| M4 | Rules (#19–#21, #27, #28) | Rules runner queues reviewable proposals only |
| M5 | Write-back (#22–#23, #32) | Approved actions apply safely and verify T+7 outcomes |
| M6 | Mobile (#24) | Approve from phone and verify |
| M7 | Hunting (#25–#26) | 10 candidates, 3 shortlisted |
| M8 | Platform hardening (#33–#37) | Copilot answers from the live system; CI green |

#31 is the standing audit issue: plan versus reality, updated whenever either changes.
