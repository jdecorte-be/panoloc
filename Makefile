.DEFAULT_GOAL := help
SHELL        := /bin/bash
POPULATE_SQL ?= sql/populate.sql
INDEXES_JS   ?= sql/indexes.js
# Strasbourg: the extent of its ground truth (data.strasbourg.eu signalisation_verticale)
# plus ~200 m, so the pictures just outside that still see its signs are kept
LOCATE_BBOX  ?= 7.540,48.439,7.848,48.704
# xmin,ymin,xmax,ymax of the pictures to import: the whole world (POPULATE_BBOX=$(LOCATE_BBOX) for Strasbourg only)
POPULATE_BBOX ?= -180,-90,180,90
COLLECTION   ?= pictures
PARQUET      ?= https://api.panoramax.xyz/data/geoparquet/panoramax.parquet
# parquet rows per DuckDB run (about 40 row groups): lower it if DuckDB still runs out of memory
BATCH_ROWS   ?= 5000000
# parquet rows to import, both included (TO_ROW empty: up to the last one); a run lists the ones of its skipped batches
FROM_ROW     ?= 0
TO_ROW       ?=
# times a failed batch is retried before it is skipped
RETRIES      ?= 2

.PHONY: help install run test lint format db-up db-down db-logs db-shell db-reset db-index populate locate web-install web-dev clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (including dev)
	uv sync

run: db-up ## Start MongoDB and the Streamlit app
	uv run streamlit run src/panoloc/app.py

test: ## Run the test suite
	uv run pytest

lint: ## Lint with ruff
	uvx ruff check src tests

format: ## Format with ruff
	uvx ruff format src tests

db-up: ## Start MongoDB in the background
	docker compose up -d --wait

db-down: ## Stop MongoDB (keeps data)
	docker compose down

db-logs: ## Follow MongoDB logs
	docker compose logs -f mongodb

db-shell: ## Open a mongosh shell in the container
	docker compose exec mongodb sh -c 'mongosh -u "$$MONGO_INITDB_ROOT_USERNAME" -p "$$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$$MONGO_INITDB_DATABASE"'

db-reset: ## Stop MongoDB and delete its data volume
	docker compose down -v

populate: db-up ## Stream the DuckDB query into MongoDB, BATCH_ROWS parquet rows per run (upserts by _id: a batch failing RETRIES more times is skipped)
	@set -o pipefail; trap 'exit 130' INT; \
	rows=$$(duckdb -noheader -list -c "SELECT num_rows FROM parquet_file_metadata('$(PARQUET)')") || exit 1; \
	to=$(if $(TO_ROW),$(TO_ROW),$$((rows - 1))); failed=(); \
	IFS=, read -r xmin ymin xmax ymax <<< "$(POPULATE_BBOX)"; \
	for ((first = $(FROM_ROW); first <= to; first += $(BATCH_ROWS))); do \
		last=$$((first + $(BATCH_ROWS) - 1)); ((last > to)) && last=$$to; \
		for ((try = 0; try <= $(RETRIES); try++)); do \
			((try)) && { echo "batch $$first-$$last failed, retry $$try/$(RETRIES) in 10 s"; sleep 10; }; \
			echo "parquet rows $$first-$$last of $$rows"; \
			{ echo "SET VARIABLE parquet = '$(PARQUET)';"; \
			  echo "SET VARIABLE first_row = $$first; SET VARIABLE last_row = $$last;"; \
			  echo "SET VARIABLE xmin = $$xmin; SET VARIABLE ymin = $$ymin; SET VARIABLE xmax = $$xmax; SET VARIABLE ymax = $$ymax;"; \
			  cat $(POPULATE_SQL); } \
			| duckdb -bail \
			| docker compose exec -T mongodb sh -c \
				'mongoimport -u "$$MONGO_INITDB_ROOT_USERNAME" -p "$$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin \
				--db "$$MONGO_INITDB_DATABASE" --collection $(COLLECTION) --mode=upsert' \
			&& continue 2; \
		done; \
		echo "batch $$first-$$last skipped, moving on to the next one"; \
		failed+=("$$first $$last"); \
	done; \
	$(MAKE) db-index || exit 1; \
	if (( $${#failed[@]} )); then \
		echo "$${#failed[@]} batch(es) skipped, import them with:"; \
		for b in "$${failed[@]}"; do echo "  make populate FROM_ROW=$${b% *} TO_ROW=$${b#* }"; done; \
		exit 1; \
	fi

db-index: ## Create the MongoDB indexes (geospatial one used by the web map)
	docker compose exec -T mongodb sh -c 'mongosh --quiet -u "$$MONGO_INITDB_ROOT_USERNAME" -p "$$MONGO_INITDB_ROOT_PASSWORD" \
		--authenticationDatabase admin "$$MONGO_INITDB_DATABASE" --file /dev/stdin' < $(INDEXES_JS)

locate: ## Locate the signs of LOCATE_BBOX ahead of the web map (cached in MongoDB)
	uv run python -m panoloc.locate $(LOCATE_BBOX)

web-install: ## Install the web app dependencies
	pnpm --dir web install

web-dev: db-up ## Start MongoDB and the Next.js map on http://localhost:3000
	pnpm --dir web dev

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
