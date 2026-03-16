# ─────────────────────────────────────────────
# Makefile – convenient shortcuts for the pipeline
# ─────────────────────────────────────────────
.PHONY: help setup up down run logs db-shell clean

help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:         ## Copy .env.example → .env (only if .env doesn't exist)
	@[ -f .env ] || cp .env.example .env && echo ".env created – edit credentials!"

up:            ## Start DB (and pgAdmin with --profile tools)
	docker compose up -d db

run:           ## Run the ETL pipeline once (builds if needed)
	docker compose run --rm etl

run-cron:      ## Run ETL in continuous/cron mode (every 24 h)
	RUN_MODE=cron docker compose up etl

logs:          ## Tail ETL logs
	docker compose logs -f etl

db-shell:      ## Open a psql shell inside the database container
	docker compose exec db psql -U $${POSTGRES_USER:-weatheruser} -d $${POSTGRES_DB:-weatherdb}

pgadmin:       ## Start pgAdmin at http://localhost:5050
	docker compose --profile tools up -d pgadmin
	@echo "pgAdmin → http://localhost:5050  (admin@weather.local / admin)"

down:          ## Stop and remove containers (data volume is preserved)
	docker compose down

clean:         ## Stop containers AND delete the data volume
	docker compose down -v
	@echo "⚠  Data volume deleted."
