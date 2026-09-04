.DEFAULT_GOAL := help

UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
NPM ?= npm
TOFU ?= tofu
TFLINT ?= tflint
CONTAINER_TOOL ?= podman
AGENT_IMAGE ?= praxis-agent:dev
AGENT_PLATFORM ?= linux/arm64
AGENT_REVISION ?= $(shell git rev-parse --verify HEAD)
HOST_CONTAINER_ARCH ?= $(shell uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')
AGENT_SMOKE_IMAGE ?= praxis-agent:smoke
AGENT_SMOKE_PLATFORM ?= linux/$(HOST_CONTAINER_ARCH)
AWS_PROFILE ?= praxis-dev
TOFU_BOOTSTRAP_PLAN ?= bootstrap.tfplan
TOFU_BOOTSTRAP_DESTROY_PLAN ?= bootstrap-destroy.tfplan
TOFU_DEV_PLAN ?= dev.tfplan
TOFU_DEV_DESTROY_PLAN ?= dev-destroy.tfplan
PROMPT ?=
SUITE ?= config
SOURCE_DATA_DIR ?= $(abspath ../barrettotte.github.io/data)
PYTHON_SOURCES := backend/src backend/tests
FRONTEND_NPM := $(NPM) --prefix frontend

export UV_CACHE_DIR

.PHONY: help bootstrap lock format format-check lint typecheck test check build tool-schemas tool-schemas-check package-api-lambda package-functions agent agent-image smoke-agent-container preview-agent-image-dev push-agent-image-dev deploy-frontend-dev eval-baseline eval-runtime-dev inspect-runtime-versions-dev tofu-init tofu-init-dev tofu-format tofu-format-check tofu-validate tofu-lint tofu-plan-bootstrap tofu-apply-bootstrap tofu-plan-destroy-bootstrap tofu-destroy-bootstrap tofu-plan-dev tofu-apply-dev tofu-plan-destroy-dev tofu-destroy-dev seed-dev smoke-dev smoke-memory-dev dev-frontend

help: ## Show the available Make targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-30s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked backend and frontend dependencies
	$(UV) sync --frozen --all-groups
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

test: ## Run backend and frontend tests
	$(UV) run pytest
	$(FRONTEND_NPM) run test

check: format-check lint typecheck test tool-schemas-check ## Run all repository quality checks

build: ## Build backend packages and the frontend production bundle
	$(UV) build
	$(FRONTEND_NPM) run build

tool-schemas: ## Generate AgentCore Gateway schemas from strict tool contracts
	./scripts/generate-agentcore-tool-schemas.sh

tool-schemas-check: ## Verify AgentCore Gateway schemas match strict tool contracts
	./scripts/generate-agentcore-tool-schemas.sh --check

package-functions: ## Build the reproducible Python 3.13 Lambda ZIP
	./scripts/package-functions.sh

package-api-lambda: ## Build the isolated Python 3.13 API Lambda ZIP
	./scripts/package-api-lambda.sh

agent: ## Run the local Strands agent; pass PROMPT='your goal'
	@test -n "$(PROMPT)" || { echo "PROMPT is required (example: make agent PROMPT='Suggest a project')"; exit 2; }
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; $(UV) run praxis "$(PROMPT)"

agent-image: ## Build the Python 3.13 ARM64 AgentCore Runtime image
	$(CONTAINER_TOOL) build --platform $(AGENT_PLATFORM) --label org.opencontainers.image.revision=$(AGENT_REVISION) --file backend/Containerfile --tag $(AGENT_IMAGE) .

smoke-agent-container: ## Verify the local AgentCore Runtime container health endpoint
	$(CONTAINER_TOOL) build --platform $(AGENT_SMOKE_PLATFORM) --label org.opencontainers.image.revision=$(AGENT_REVISION) --file backend/Containerfile --tag $(AGENT_SMOKE_IMAGE) .
	CONTAINER_TOOL=$(CONTAINER_TOOL) AGENT_IMAGE=$(AGENT_SMOKE_IMAGE) AGENT_PLATFORM=$(AGENT_SMOKE_PLATFORM) ./scripts/smoke/smoke-agent-container.sh

preview-agent-image-dev: ## Preview the immutable development ECR image publication
	ACTION=preview AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) CONTAINER_TOOL=$(CONTAINER_TOOL) AGENT_IMAGE=$(AGENT_IMAGE) ./scripts/push-agent-image-dev.sh

push-agent-image-dev: ## Push the reviewed image to ECR; requires CONFIRM=push-agent-image-dev
	ACTION=push CONFIRM=$(CONFIRM) AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) CONTAINER_TOOL=$(CONTAINER_TOOL) AGENT_IMAGE=$(AGENT_IMAGE) ./scripts/push-agent-image-dev.sh

deploy-frontend-dev: ## Build and publish the frontend; requires CONFIRM=deploy-frontend-dev
	CONFIRM=$(CONFIRM) AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) ./scripts/deploy-frontend-dev.sh

eval-baseline: ## Run the project-recommendation model baseline and save versioned results
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; $(UV) run python -m praxis.evaluation

eval-runtime-dev: ## Measure all evaluation cases against the deployed stable Runtime
	AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) SOURCE_DATA_DIR=$(SOURCE_DATA_DIR) ./scripts/eval-runtime-dev.sh

inspect-runtime-versions-dev: ## List sanitized immutable Runtime version metadata
	AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) ./scripts/inspect-runtime-versions-dev.sh

tofu-init: ## Install pinned providers without initializing a remote backend
	$(TOFU) -chdir=infra/bootstrap init -backend=false
	$(TOFU) -chdir=infra/environments/dev init -backend=false

tofu-init-dev: ## Initialize development state with the bootstrap S3 backend
	@state_bucket="$$(AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/bootstrap output -raw state_bucket_name)"; \
		test -n "$$state_bucket"; \
		AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/environments/dev init -reconfigure -backend-config="bucket=$$state_bucket"

tofu-format: ## Format all OpenTofu configuration
	$(TOFU) fmt -recursive infra

tofu-format-check: ## Verify OpenTofu formatting
	$(TOFU) fmt -check -recursive infra

tofu-validate: tool-schemas-check package-functions package-api-lambda ## Validate the bootstrap and development OpenTofu roots
	$(TOFU) -chdir=infra/bootstrap validate
	$(TOFU) -chdir=infra/environments/dev validate

tofu-lint: ## Run TFLint static analysis across OpenTofu configuration
	$(TFLINT) --recursive --chdir=infra --config=$(CURDIR)/.tflint.hcl

tofu-plan-bootstrap: ## Plan durable bootstrap resources without applying them
	@test "$(TOFU_BOOTSTRAP_PLAN)" = "$(notdir $(TOFU_BOOTSTRAP_PLAN))" || { echo "TOFU_BOOTSTRAP_PLAN must be a file name"; exit 2; }
	$(RM) infra/bootstrap/$(TOFU_BOOTSTRAP_PLAN)
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/bootstrap plan -out=$(TOFU_BOOTSTRAP_PLAN)

tofu-apply-bootstrap: ## Apply the reviewed bootstrap plan; requires CONFIRM=apply-bootstrap
	@test "$(CONFIRM)" = "apply-bootstrap" || { echo "CONFIRM=apply-bootstrap is required"; exit 2; }
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/bootstrap apply $(TOFU_BOOTSTRAP_PLAN)

tofu-plan-destroy-bootstrap: ## Plan permanent bootstrap teardown without applying it
	@test "$(TOFU_BOOTSTRAP_DESTROY_PLAN)" = "$(notdir $(TOFU_BOOTSTRAP_DESTROY_PLAN))" || { echo "TOFU_BOOTSTRAP_DESTROY_PLAN must be a file name"; exit 2; }
	$(RM) infra/bootstrap/$(TOFU_BOOTSTRAP_DESTROY_PLAN)
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/bootstrap plan -destroy -out=$(TOFU_BOOTSTRAP_DESTROY_PLAN)

tofu-destroy-bootstrap: ## Apply the reviewed bootstrap teardown; requires CONFIRM=destroy-bootstrap
	@test "$(CONFIRM)" = "destroy-bootstrap" || { echo "CONFIRM=destroy-bootstrap is required"; exit 2; }
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/bootstrap apply $(TOFU_BOOTSTRAP_DESTROY_PLAN)

tofu-plan-dev: tool-schemas-check package-functions package-api-lambda ## Plan temporary development resources without applying them
	@test "$(TOFU_DEV_PLAN)" = "$(notdir $(TOFU_DEV_PLAN))" || { echo "TOFU_DEV_PLAN must be a file name"; exit 2; }
	$(RM) infra/environments/dev/$(TOFU_DEV_PLAN)
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/environments/dev plan -out=$(TOFU_DEV_PLAN)

tofu-apply-dev: ## Apply the reviewed development plan; requires CONFIRM=apply-dev
	@test "$(CONFIRM)" = "apply-dev" || { echo "CONFIRM=apply-dev is required"; exit 2; }
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/environments/dev apply $(TOFU_DEV_PLAN)

tofu-plan-destroy-dev: tool-schemas-check package-functions package-api-lambda ## Plan temporary development teardown without applying it
	@test "$(TOFU_DEV_DESTROY_PLAN)" = "$(notdir $(TOFU_DEV_DESTROY_PLAN))" || { echo "TOFU_DEV_DESTROY_PLAN must be a file name"; exit 2; }
	$(RM) infra/environments/dev/$(TOFU_DEV_DESTROY_PLAN)
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/environments/dev plan -destroy -out=$(TOFU_DEV_DESTROY_PLAN)

tofu-destroy-dev: ## Apply the reviewed development teardown; requires CONFIRM=destroy-dev
	@test "$(CONFIRM)" = "destroy-dev" || { echo "CONFIRM=destroy-dev is required"; exit 2; }
	AWS_PROFILE=$(AWS_PROFILE) $(TOFU) -chdir=infra/environments/dev apply $(TOFU_DEV_DESTROY_PLAN)

seed-dev: ## Upload authoritative JSON and invoke ingestion; requires CONFIRM=seed-dev
	CONFIRM=$(CONFIRM) AWS_PROFILE=$(AWS_PROFILE) TOFU=$(TOFU) SOURCE_DATA_DIR=$(SOURCE_DATA_DIR) ./scripts/seed-dev.sh

smoke-dev: ## Run a deployed smoke suite; SUITE defaults to config
	AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) PROMPT="$(PROMPT)" ./scripts/smoke/smoke-dev.sh "$(SUITE)"

smoke-memory-dev: ## Verify typed AgentCore Memory; requires CONFIRM=smoke-memory-dev
	CONFIRM=$(CONFIRM) AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=us-east-1 TOFU=$(TOFU) ./scripts/smoke/smoke-memory-dev.sh

dev-frontend: ## Start the frontend development server
	$(FRONTEND_NPM) run dev
