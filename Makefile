.PHONY: help up down restart logs ps psql migrate seed test fmt lint dbt clean

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
PSQL_URL := $(shell grep -E '^DATABASE_URL=' .env 2>/dev/null | cut -d= -f2-)

help:
	@echo "up        start postgres, redis, metabase"
	@echo "down      stop containers (data volumes preserved)"
	@echo "logs      tail all container logs"
	@echo "psql      open a psql shell on the analytics database"
	@echo "migrate   apply packages/db/migrations in order"
	@echo "seed      insert tenant #1 and the 8 starter rules"
	@echo "test      run pytest (includes the RLS isolation gate)"
	@echo "dbt       run dbt build"
	@echo "clean     stop containers AND delete volumes (destructive)"

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
	@for f in $$(ls packages/db/migrations/*.sql | sort); do \
		echo "applying $$f"; \
		$(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -U $${POSTGRES_USER:-axaty} -d $${POSTGRES_DB:-axaty} < $$f || exit 1; \
	done
	@echo "migrations applied"

seed:
	python -m packages.db.seed

test:
	pytest -q

fmt:
	ruff format .

lint:
	ruff check .

dbt:
	cd packages/dbt && dbt build

clean:
	$(COMPOSE) down -v
	@echo "volumes deleted"
