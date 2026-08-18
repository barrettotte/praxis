.DEFAULT_GOAL := help

UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
NPM ?= npm
PROMPT ?=
PYTHON_SOURCES := backend/src backend/tests
FRONTEND_NPM := $(NPM) --prefix frontend

export UV_CACHE_DIR

.PHONY: help bootstrap lock format format-check lint typecheck test check build agent dev-frontend

help: ## Show the available Make targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked backend and frontend dependencies
	$(UV) sync --all-groups
	$(FRONTEND_NPM) ci

lock: ## Refresh the backend and frontend dependency lock files
	$(UV) lock
	$(FRONTEND_NPM) install --package-lock-only

format: ## Format backend and frontend source files
	$(UV) run ruff check --fix $(PYTHON_SOURCES)
	$(UV) run ruff format $(PYTHON_SOURCES)
	$(FRONTEND_NPM) run format

format-check: ## Verify backend and frontend formatting
	$(UV) run ruff format --check $(PYTHON_SOURCES)
	$(FRONTEND_NPM) run format:check

lint: ## Lint backend and frontend source files
	$(UV) run ruff check $(PYTHON_SOURCES)
	$(FRONTEND_NPM) run lint

typecheck: ## Type-check the backend and frontend
	$(UV) run pyright
	$(FRONTEND_NPM) run typecheck

test: ## Run backend and frontend unit tests
	$(UV) run pytest
	$(FRONTEND_NPM) run test

check: format-check lint typecheck test ## Run all repository quality checks

build: ## Build backend packages and the frontend production bundle
	$(UV) build
	$(FRONTEND_NPM) run build

agent: ## Run the local Strands agent; pass PROMPT='your goal'
	@test -n "$(PROMPT)" || { echo "PROMPT is required (example: make agent PROMPT='Suggest a project')"; exit 2; }
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; $(UV) run praxis "$(PROMPT)"

dev-frontend: ## Start the frontend development server
	$(FRONTEND_NPM) run dev
