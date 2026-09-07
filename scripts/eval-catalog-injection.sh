#!/usr/bin/env bash
# Verify that instruction-bearing catalog text cannot override agent behavior.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/smoke/lib/dev-smoke.sh"

praxis_require_commands aws jq "${praxis_tofu}" uv

# Use the exact model and guardrail attached to the live Runtime.
praxis_runtime_id="$(praxis_tofu_output agentcore_runtime_id)"
praxis_runtime_version="$(praxis_runtime_endpoint_version)"
praxis_runtime_environment="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "${praxis_runtime_id}" \
    --agent-runtime-version "${praxis_runtime_version}" \
    --query environmentVariables --output json
)"
praxis_model_id="$(jq -er '.PRAXIS_MODEL_ID' <<<"${praxis_runtime_environment}")"
praxis_guardrail_id="$(jq -er '.PRAXIS_GUARDRAIL_ID' <<<"${praxis_runtime_environment}")"
praxis_guardrail_version="$(
  jq -er '.PRAXIS_GUARDRAIL_VERSION' <<<"${praxis_runtime_environment}"
)"

AWS_PROFILE="${praxis_profile}" UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" \
  uv run --project "${praxis_repo_root}" python -m praxis.evaluation.catalog_injection \
  --region "${praxis_region}" \
  --model-id "${praxis_model_id}" \
  --guardrail-id "${praxis_guardrail_id}" \
  --guardrail-version "${praxis_guardrail_version}" \
  --evidence-directory "${praxis_repo_root}/build/evals"
