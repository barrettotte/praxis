#!/usr/bin/env bash
# Invoke the stable AgentCore Runtime endpoint with a signed development request.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_prompt="${PROMPT:-compiler}"
praxis_timeout_seconds="${RUNTIME_SMOKE_TIMEOUT_SECONDS:-180}"
praxis_verify_session_isolation="${VERIFY_SESSION_ISOLATION:-false}"
praxis_verify_traces="${VERIFY_RUNTIME_TRACES:-false}"
praxis_trace_timeout_seconds="${RUNTIME_TRACE_TIMEOUT_SECONDS:-180}"

# Resolve the Runtime and its immutable qualifier from deployed OpenTofu state.
printf 'Resolving the deployed Runtime endpoint...\n' >&2
praxis_runtime_arn="$(praxis_tofu_output agentcore_runtime_arn)"
praxis_endpoint_name="$(praxis_tofu_output agentcore_runtime_endpoint_name)"
praxis_endpoint_version="$(praxis_tofu_output agentcore_runtime_endpoint_version)"

printf 'Invoking Runtime endpoint %s at version %s (timeout: %ss)...\n' \
  "${praxis_endpoint_name}" "${praxis_endpoint_version}" "${praxis_timeout_seconds}" >&2

# Bound the entire buffered request, including Runtime startup and model/tool cycles.
praxis_arguments=()
praxis_command_timeout_seconds="${praxis_timeout_seconds}"
if [[ "${praxis_verify_session_isolation}" == "true" ]]; then
  praxis_arguments+=(--verify-session-isolation)
fi
if [[ "${praxis_verify_traces}" == "true" ]]; then
  praxis_arguments+=(--verify-traces --trace-timeout-seconds "${praxis_trace_timeout_seconds}")
  praxis_command_timeout_seconds="$((praxis_timeout_seconds + praxis_trace_timeout_seconds))"
fi
UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" timeout --foreground "${praxis_command_timeout_seconds}s" \
  uv run --project "${praxis_repo_root}" \
  python -m praxis.agent.runtime_smoke \
  --runtime-arn "${praxis_runtime_arn}" \
  --qualifier "${praxis_endpoint_name}" \
  --endpoint-version "${praxis_endpoint_version}" \
  --profile "${praxis_profile}" \
  --region "${praxis_region}" \
  --prompt "${praxis_prompt}" \
  "${praxis_arguments[@]}" \
  --evidence-directory "${praxis_repo_root}/docs/evidence"
