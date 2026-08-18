.DEFAULT_GOAL := help

UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
PROMPT ?=
PYTHON_SOURCES := backend/src backend/tests

export UV_CACHE_DIR

.PHONY: help bootstrap lock format format-check lint typecheck test check build agent

help: ## Show the available Make targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install the Python 3.13 environment and locked dependencies
	$(UV) sync --all-groups

lock: ## Refresh the Python dependency lock file
	$(UV) lock

format: ## Format Python source and test files with Ruff
	$(UV) run ruff format $(PYTHON_SOURCES)
	$(UV) run ruff check --fix $(PYTHON_SOURCES)

format-check: ## Verify Python formatting without changing files
	$(UV) run ruff format --check $(PYTHON_SOURCES)

lint: ## Run the configured Ruff lint rules
	$(UV) run ruff check $(PYTHON_SOURCES)

typecheck: ## Run strict Pyright type checking
	$(UV) run pyright

test: ## Run the backend unit tests
	$(UV) run pytest

check: format-check lint typecheck test ## Run all backend quality checks

build: ## Build the backend source distribution and wheel
	$(UV) build

agent: ## Run the local Strands agent; pass PROMPT='your goal'
	@test -n "$(PROMPT)" || { echo "PROMPT is required (example: make agent PROMPT='Suggest a project')"; exit 2; }
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; $(UV) run praxis "$(PROMPT)"
