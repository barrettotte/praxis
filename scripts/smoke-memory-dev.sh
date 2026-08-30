#!/usr/bin/env bash
# Verify typed preference and decision records in deployed AgentCore Memory.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"

# This check can create two metered records, so it always requires the user to opt in.
if [[ "${CONFIRM:-}" != "smoke-memory-dev" ]]; then
  printf 'CONFIRM=smoke-memory-dev is required\n' >&2
  exit 2
fi

# Resolve the deployed identifier without placing account details in configuration.
praxis_memory_id="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_memory_id
)"

UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv run --project "${praxis_repo_root}" \
  python -m praxis.agent.memory_smoke \
  --memory-id "${praxis_memory_id}" \
  --profile "${praxis_profile}" \
  --region "${praxis_region}" \
  --evidence-directory "${praxis_repo_root}/docs/evidence"
