#!/usr/bin/env bash
# Check Gateway authorization, discovery, and a catalog round trip.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
# Read the deployed endpoint from state instead of duplicating environment values.
praxis_gateway_url="$(praxis_tofu_output agentcore_gateway_url)"

UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv run --project "${praxis_repo_root}" \
  python -m praxis.gateway_smoke \
  --url "${praxis_gateway_url}" \
  --profile "${praxis_profile}" \
  --region "${praxis_region}"
