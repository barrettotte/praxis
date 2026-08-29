#!/usr/bin/env bash
# Exercise the local Strands agent against the deployed IAM-authenticated Gateway.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
# Export optional local agent settings for the configuration read below.
if [[ -f "${praxis_repo_root}/.env" ]]; then
  set -a
  source "${praxis_repo_root}/.env"
  set +a
fi
praxis_model_id="${PRAXIS_MODEL_ID:-}"
praxis_max_catalog_results="${PRAXIS_MAX_CATALOG_RESULTS:-20}"
praxis_max_tool_calls="${PRAXIS_MAX_TOOL_CALLS:-4}"
praxis_prompt="${PROMPT:-Call search_catalog once with query 'compiler' and limit 3. Then return exactly three learning-project candidates using only the returned evidence.}"
if [[ -z "${praxis_model_id}" ]]; then
  printf 'PRAXIS_MODEL_ID is required; set it in .env or the environment\n' >&2
  exit 2
fi
# Read the deployed endpoint from state instead of duplicating environment values.
praxis_gateway_url="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_repo_root}/infra/environments/dev" \
    output -raw agentcore_gateway_url
)"

UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv run --project "${praxis_repo_root}" \
  python -m praxis.agent.gateway_smoke \
  --url "${praxis_gateway_url}" \
  --profile "${praxis_profile}" \
  --region "${praxis_region}" \
  --model-id "${praxis_model_id}" \
  --max-catalog-results "${praxis_max_catalog_results}" \
  --max-tool-calls "${praxis_max_tool_calls}" \
  --prompt "${praxis_prompt}" \
  --evidence-directory "${praxis_repo_root}/docs/evidence"
