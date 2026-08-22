# ADR 003 - Migrations: ledger, checksums, and when a down file is required

**Status:** accepted, 22 Aug 2026

## Context

The first migration setup was one line of shell:

```make
for f in $(ls packages/db/migrations/*.sql | sort); do psql -v ON_ERROR_STOP=1 < $f; done
```

It replayed every file on every run. That is only safe if every statement in
every file is idempotent forever, which nothing enforced and no test checked.
With `ON_ERROR_STOP=1`, the second `make migrate` would abort at the first
`create table` without `if not exists` -- partway through, with no record of
what had been applied.

The audit that found this also found the reason it went unnoticed: the
migrations had **never been run**. `make migrate` is the first command a new
contributor types, and it was the least verified thing in the repo.

## Decision

A Python runner, `packages/db/migrate.py`, with four commands: `status`,
`up`, `down`, `baseline`.

1. **Ledger.** `schema_migrations (version, name, checksum, applied_at)`. Only
   unapplied versions run, so a second `up` is a real no-op rather than a
   hopeful one.
2. **Checksums.** Editing an applied migration is a hard error, not a silent
   re-run. Amend by adding a new migration.
3. **One transaction per migration**, not one for the batch. A failure at 0004
   cannot undo 0003, and the ledger always describes the real schema.
4. **Filename discipline.** `NNNN_snake_case.sql`, enforced at discovery.
   Duplicate versions are a hard error.
5. **`baseline`** records files as applied without running them, for a database
   already migrated by the old shell loop. One-time bridge, not a repair tool.

### When a down file is required

- **Structural migrations** (new tables, policies, columns) ship a down file in
  `packages/db/migrations/down/` with the same filename.
- **Repairs** may not have a literal inverse. `0004_fix_changes_today.sql`
  replaced a view whose delta read the wrong JSON key, so the guardrail it fed
  always passed. Its down file drops the view rather than restoring the broken
  definition: reverting to a defect that took a cross-read to find is not a
  service to anyone. Re-running `up` recreates the fixed view.
- `down` **refuses** to step over a migration with no down file. It does not
  guess and does not skip. For a full local reset use `make clean`, which drops
  the volumes -- that is the honest reset path, not a chain of down migrations.

## Why not dbmate / Alembic / Flyway

dbmate is a good tool and does exactly this. It was rejected for one reason:
it is a separate binary to install and pin on every machine, and this project
is run on one PC today with a Hetzner box later. Alembic assumes SQLAlchemy
models, and this schema is hand-written SQL with RLS policies that Alembic's
autogenerate cannot see. Flyway needs a JVM.

The runner is ~200 lines with no dependency beyond psycopg, which is already
required. If a second engineer joins or CI grows, revisit dbmate -- the ledger
table shape here is deliberately close to what dbmate uses, to keep that door
open.

## Consequences

- `make migrate` is now safe to run repeatedly. This is the property #29 asked
  for and the acceptance test is exactly that: run it twice, second run applies
  nothing.
- Migrations run from the **host** against `DATABASE_URL`, not inside the
  container. The same command therefore works against a remote database later.
  It also means the host needs psycopg installed, which the tests already need.
- `marts` schema objects are still created by dbt, not by migrations. Two
  systems own two schemas; do not let them overlap.
