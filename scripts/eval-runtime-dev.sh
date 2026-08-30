#!/usr/bin/env bash
# Measure the canonical project evaluation against the stable development Runtime.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_trace_timeout_seconds="${RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS:-180}"
praxis_data_dir="${SOURCE_DATA_DIR:-${praxis_repo_root}/../barrettotte.github.io/data}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"

for praxis_command in "${praxis_tofu}" aws jq uv; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command not found: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# Resolve only reproducibility metadata exposed by the reviewed OpenTofu state.
praxis_runtime_arn="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_runtime_arn
)"
praxis_runtime_id="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_runtime_id
)"
praxis_endpoint_name="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_runtime_endpoint_name
)"
praxis_endpoint_version="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_runtime_endpoint_version
)"
# Read model and image identity from the immutable version served by the endpoint.
praxis_runtime_metadata="$(
  AWS_PROFILE="${praxis_profile}" aws bedrock-agentcore-control get-agent-runtime \
    --region "${praxis_region}" \
    --agent-runtime-id "${praxis_runtime_id}" \
    --agent-runtime-version "${praxis_endpoint_version}" \
    --query '{status:status,model:environmentVariables.PRAXIS_MODEL_ID,container:agentRuntimeArtifact.containerConfiguration.containerUri}' \
    --output json
)"
praxis_runtime_status="$(jq -er '.status' <<<"${praxis_runtime_metadata}")"
praxis_model_id="$(jq -er '.model' <<<"${praxis_runtime_metadata}")"
praxis_container_uri="$(jq -er '.container' <<<"${praxis_runtime_metadata}")"
praxis_container_digest="${praxis_container_uri##*@}"

if [[ "${praxis_runtime_status}" != "READY" ]]; then
  printf 'Runtime endpoint version is not READY: %s\n' "${praxis_runtime_status}" >&2
  exit 2
fi
if [[ ! "${praxis_container_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'Runtime container URI is not pinned by SHA-256 digest.\n' >&2
  exit 2
fi
if [[ ! "${praxis_trace_timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi

printf 'Evaluating Runtime endpoint %s at version %s with %s.\n' \
  "${praxis_endpoint_name}" "${praxis_endpoint_version}" "${praxis_model_id}" >&2
printf 'Each of the ten cases invokes a fresh metered Runtime session and waits for its trace.\n' >&2

# Keep prompts isolated while recording only sanitized endpoint and image identities.
UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv run --project "${praxis_repo_root}" \
  python -m praxis.evaluation.runtime \
  --runtime-arn "${praxis_runtime_arn}" \
  --qualifier "${praxis_endpoint_name}" \
  --runtime-version "${praxis_endpoint_version}" \
  --container-digest "${praxis_container_digest}" \
  --model-id "${praxis_model_id}" \
  --region "${praxis_region}" \
  --profile "${praxis_profile}" \
  --trace-timeout-seconds "${praxis_trace_timeout_seconds}" \
  --data-dir "${praxis_data_dir}"
