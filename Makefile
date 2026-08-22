.PHONY: help up down restart logs ps psql migrate migrate-status migrate-down migrate-baseline testdb migrate-test seed test fmt lint dbt clean

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
# Migrations run from the host against DATABASE_URL, so .env has to be in the
# environment of the python process, not just of docker compose.
ENV := set -a; . ./.env; set +a;
STEPS ?= 1

help:
	@echo "up                start postgres, redis, metabase"
	@echo "down              stop containers (data volumes preserved)"
	@echo "logs              tail all container logs"
	@echo "ps                show container status"
	@echo "psql              open a psql shell on the analytics database"
	@echo ""
	@echo "migrate           apply pending migrations (ledger-tracked, safe to re-run)"
	@echo "migrate-status    show applied vs pending, and which have a down file"
	@echo "migrate-down      revert the last migration (STEPS=2 for more)"
	@echo "migrate-baseline  adopt a DB already migrated by the old shell loop"
	@echo ""
	@echo "testdb            create the test database"
	@echo "migrate-test      apply migrations to TEST_DATABASE_URL"
	@echo "seed              insert tenants and the starter rules"
	@echo "test              run pytest (includes the RLS isolation gate)"
	@echo "dbt               run dbt build"
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

migrate:
	@$(ENV) python -m packages.db.migrate up

migrate-status:
	@$(ENV) python -m packages.db.migrate status

migrate-down:
	@$(ENV) python -m packages.db.migrate down --steps $(STEPS)

migrate-baseline:
	@$(ENV) python -m packages.db.migrate baseline

# The engine tests create tables in the marts schema, so they deliberately
# refuse to touch DATABASE_URL and require TEST_DATABASE_URL instead.
testdb:
	@$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-axaty} -d postgres \
		-c "create database $${TEST_DB_NAME:-axaty_test}" || echo "test database already exists"

migrate-test:
	@$(ENV) DATABASE_URL=$$TEST_DATABASE_URL python -m packages.db.migrate up

seed:
	@$(ENV) python -m packages.db.seed

test:
	@$(ENV) pytest -q

fmt:
	ruff format .

lint:
	ruff check .

dbt:
	cd packages/dbt && dbt build

clean:
	$(COMPOSE) down -v
	@echo "volumes deleted"
