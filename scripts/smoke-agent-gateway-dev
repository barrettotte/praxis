#!/usr/bin/env bash
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
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
  --evidence-directory "${praxis_repo_root}/docs/evidence"
