.PHONY: help up down restart logs ps psql sync migrate migrate-status migrate-down migrate-baseline testdb migrate-test seed seed-spapi-sandbox-demo test fmt lint dbt backup-postgres verify-postgres-backup raw-monthly-coverage rotate-token-vault actions actions-live reports scheduler scheduler-history scheduler-catch-up clean

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
ENV := set -a; . ./.env; set +a;
STEPS ?= 1
TENANT_ID ?= $${DEV_TENANT_ID}

help:
	@echo "up                start postgres, redis, metabase"
	@echo "down              stop containers (data volumes preserved)"
	@echo "logs              tail all container logs"
	@echo "ps                show container status"
	@echo "psql              open a psql shell on the analytics database"
	@echo ""
	@echo "migrate           apply pending migrations (ledger-tracked, safe to re-run)"
	@echo "sync              install locked Python dependencies from uv.lock"
	@echo "migrate-status    show applied vs pending, and which have a down file"
	@echo "migrate-down      revert the last migration (STEPS=2 for more)"
	@echo "migrate-baseline  adopt a DB already migrated by the old shell loop"
	@echo ""
	@echo "testdb            create the test database"
	@echo "migrate-test      apply migrations to TEST_DATABASE_URL"
	@echo "backup-postgres   write a verified custom-format backup (BACKUP_DIR=...)"
	@echo "verify-postgres-backup restore into an empty *_scratch or *_restore DB (BACKUP_FILE=...)"
	@echo "raw-monthly-coverage export per-tenant raw row counts by month (REPORT_DIR=...)"
	@echo "rotate-token-vault dry-run one tenant; APPLY=true persists rewraps (TENANT_ID=...)"
	@echo "seed              insert tenants and the starter rules"
	@echo "seed-spapi-sandbox-demo  load clearly labelled local SP-API sandbox fixtures"
	@echo "test              run pytest (includes the RLS isolation gate)"
	@echo "dbt               run dbt build"
	@echo ""
	@echo "actions           run approved-action worker in dry-run mode"
	@echo "actions-live      run approved-action worker with live Ads writes"
	@echo "reports           render one queued governed report"
	@echo "scheduler         run ingestion/rules scheduler once"
	@echo "scheduler-history show recent pipeline run history"
	@echo "scheduler-catch-up show rolling catch-up gaps"
	@echo ""
	@echo "clean             stop containers AND delete volumes (destructive)"

up:
	$(COMPOSE) up -d
	@echo "waiting for postgres..."
	@until $(COMPOSE) exec -T postgres pg_isready -q; do sleep 1; done
	@echo "stack is up. metabase: http://localhost:3001"

down:
	$(COMPOSE) down

restart: down up

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

psql:
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-axaty} -d $${POSTGRES_DB:-axaty}

sync:
	uv sync --locked --extra dev

migrate:
	@$(ENV) uv run --locked python -m packages.db.migrate up

migrate-status:
	@$(ENV) uv run --locked python -m packages.db.migrate status

migrate-down:
	@$(ENV) uv run --locked python -m packages.db.migrate down --steps $(STEPS)

migrate-baseline:
	@$(ENV) uv run --locked python -m packages.db.migrate baseline

testdb:
	@$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-axaty} -d postgres \
		-c "create database $${TEST_DB_NAME:-axaty_test}" || echo "test database already exists"

migrate-test:
	@$(ENV) DATABASE_URL=$$TEST_DATABASE_URL uv run --locked python -m packages.db.migrate up

backup-postgres:
	@$(ENV) uv run --locked python infra/scripts/backup_postgres.py --output-dir "$${BACKUP_DIR:-.data/backups}"

verify-postgres-backup:
	@$(ENV) uv run --locked python infra/scripts/verify_postgres_restore.py --backup "$${BACKUP_FILE:?set BACKUP_FILE to a .dump file}"

raw-monthly-coverage:
	@$(ENV) uv run --locked python infra/scripts/report_raw_monthly_coverage.py --output-dir "$${REPORT_DIR:-.data/raw-coverage}"

rotate-token-vault:
	@$(ENV) uv run --locked python -m services.ingest.security.rotate_vault --tenant-id "$(TENANT_ID)" $(if $(filter true,$(APPLY)),--apply,)

seed:
	@$(ENV) uv run --locked python -m packages.db.seed

seed-spapi-sandbox-demo:
	@$(ENV) uv run --locked python -m packages.db.seed_spapi_sandbox_demo

test:
	@$(ENV) uv run --locked --extra dev pytest -q

fmt:
	uv run --locked --extra dev ruff format .

lint:
	uv run --locked --extra dev ruff check .

dbt:
	cd packages/dbt && uv run --locked dbt build

actions:
	@$(ENV) uv run --locked python -m services.actions.worker --tenant-id $(TENANT_ID)

actions-live:
	@$(ENV) uv run --locked python -m services.actions.worker --tenant-id $(TENANT_ID) --live-ads

reports:
	@$(ENV) uv run --locked python -m services.reports.worker --tenant-id $(TENANT_ID)

scheduler:
	@$(ENV) uv run --locked python -m services.scheduler.runner --tenant-id $(TENANT_ID)

scheduler-history:
	@$(ENV) uv run --locked python -m services.scheduler.runner --tenant-id $(TENANT_ID) --show-history --skip-rules

scheduler-catch-up:
	@$(ENV) uv run --locked python -m services.scheduler.runner --tenant-id $(TENANT_ID) --show-catch-up --skip-rules

clean:
	$(COMPOSE) down -v
	@echo "volumes deleted"
