.DEFAULT_GOAL := help

ROOT := $(shell pwd)
COMPOSE := docker compose -f infra/docker/docker-compose.yml

# ── Help ───────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Local stack ────────────────────────────────────────────────────────────
up: ## Start local stack (Kafka + Schema Registry; more services arrive with later stages)
	$(COMPOSE) up -d

down: ## Stop local stack
	$(COMPOSE) down

logs: ## Tail local stack logs
	$(COMPOSE) logs -f --tail=100

# ── Data lifecycle ─────────────────────────────────────────────────────────
seed: ## Seed Bronze with Synthea + Kaggle samples
	./scripts/seed_data.sh

ingest: ## Run a one-off Bronze ingest cycle
	uv run polaris-ingest run --source synthea

stream: ## Start the FNOL Kafka producer (Ctrl-C to stop)
	uv run python streaming/fnol_producer/src/main.py --rate 10

# ── Transform ──────────────────────────────────────────────────────────────
dbt-build: ## Run full dbt build (run + test)
	cd dbt && dbt build --target dev

dbt-test: ## Run dbt tests only
	cd dbt && dbt test --target dev

ge-run: ## Run the RAW Great Expectations checkpoint (needs Stage 5 RAW tables)
	cd quality/great_expectations && uv run great_expectations checkpoint run raw_polaris

# ── Infra (Snowflake Terraform; run init once first) ─────────────────────────
tf-init: ## terraform init for the Snowflake stack
	terraform -chdir=infra/terraform/snowflake init

tf-plan: ## terraform plan for the Snowflake stack (writes tfplan)
	terraform -chdir=infra/terraform/snowflake plan -out tfplan

tf-apply: ## Apply the saved tfplan
	terraform -chdir=infra/terraform/snowflake apply tfplan

# ── Code quality ───────────────────────────────────────────────────────────
lint: ## Lint everything (ruff + sqlfluff + terraform fmt-check)
	uv run ruff check .
	uv run sqlfluff lint dbt/models
	terraform -chdir=infra/terraform fmt -check -recursive

fmt: ## Format everything
	uv run ruff format .
	uv run sqlfluff fix dbt/models
	terraform -chdir=infra/terraform fmt -recursive

test: ## Run all unit tests
	uv run pytest

# ── Bootstrap ──────────────────────────────────────────────────────────────
bootstrap: ## One-time: install pre-commit hooks + python deps
	uv sync --all-extras
	uv run pre-commit install

.PHONY: help up down logs seed ingest stream dbt-build dbt-test ge-run tf-init tf-plan tf-apply lint fmt test bootstrap
